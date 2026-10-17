import { execFile } from "node:child_process";
import { freemem, totalmem } from "node:os";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";
import { definePlugin } from "./sdk/index.mjs";

const execFileAsync = promisify(execFile);
const GIB = 1024 ** 3;

export const DEFAULT_POLICY = Object.freeze({
	maxConcurrentRuns: 2,
	minFreeRamBytes: 12 * GIB,
	minFreeVramBytes: 6 * GIB,
	maxGpuEngineBusyPct: 85,
	monitorIntervalMs: 5000,
});

export function hasConcurrencyHeadroom(metrics, policy = DEFAULT_POLICY) {
	return Boolean(
		metrics &&
		Number.isFinite(metrics.ramAvailableBytes) &&
		Number.isFinite(metrics.gpuFreeBytes) &&
		Number.isFinite(metrics.gpuPeakEngineBusyPct) &&
		metrics.ramAvailableBytes >= policy.minFreeRamBytes &&
		metrics.gpuFreeBytes >= policy.minFreeVramBytes &&
		metrics.gpuPeakEngineBusyPct < policy.maxGpuEngineBusyPct,
	);
}

export function selectOldestRun(activeRuns) {
	const entries = activeRuns instanceof Map ? [...activeRuns.entries()] : [...activeRuns];
	entries.sort((a, b) => a[1].startedAt - b[1].startedAt);
	return entries.length ? { id: entries[0][0], ...entries[0][1] } : null;
}

export async function readResourceSnapshot() {
	const script = fileURLToPath(new URL("./resource-snapshot.ps1", import.meta.url));
	const { stdout } = await execFileAsync(
		"powershell.exe",
		["-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", script],
		{ timeout: 10000, maxBuffer: 16 * 1024, windowsHide: true },
	);
	const gpu = JSON.parse(stdout.trim());
	return {
		...gpu,
		ramAvailableBytes: freemem(),
		ramTotalBytes: totalmem(),
	};
}

export function createCapacityManager(host, {
	snapshotProvider = readResourceSnapshot,
	policy = DEFAULT_POLICY,
} = {}) {
	const active = new Map();
	let decisionTail = Promise.resolve();
	let monitor = null;

	function log(level, message) {
		try {
			host.log(level, message);
		} catch {
			// A diagnostic failure must never affect the agent run.
		}
	}

	function syncMonitor() {
		if (active.size > 1 && !monitor) {
			monitor = setInterval(() => enqueue(), policy.monitorIntervalMs);
			monitor.unref?.();
		} else if (active.size <= 1 && monitor) {
			clearInterval(monitor);
			monitor = null;
		}
	}

	async function reconcile() {
		if (active.size <= 1) return;

		let metrics = null;
		try {
			metrics = await snapshotProvider();
		} catch (error) {
			log("warn", `Resource telemetry unavailable; using single-run mode: ${error.message}`);
		}

		while (active.size > 1) {
			const overLimit = active.size > policy.maxConcurrentRuns;
			if (!overLimit && hasConcurrencyHeadroom(metrics, policy)) break;

			const victim = selectOldestRun(active);
			if (!victim) break;

			try {
				const result = await host.abortRun(victim.id);
				if (result?.ok === false) {
					log("error", `Could not interrupt run ${victim.id}: ${result.error ?? "abort rejected"}`);
					const record = active.get(victim.id);
					const error = result.error ?? "abort rejected";
					if (record && record.abortError !== error) {
						record.abortError = error;
						try {
							host.notify("error", `Compute guard could not interrupt the oldest run: ${error}. No session was deleted. Stop the older run manually before starting more work.`);
						} catch {}
					}
					break;
				}

				active.delete(victim.id);
				const seconds = Math.max(0, Math.round((Date.now() - victim.startedAt) / 1000));
				const label = victim.conversationId ?? victim.id;
				const message = `Compute guard interrupted the oldest active Pi run (${label}, active about ${seconds}s). Its transcript and partial answer were retained; reopen that conversation to continue.`;
				log("warn", message);
				try {
					host.notify("warning", message);
				} catch {}

				if (active.size <= 1) break;
				try {
					metrics = await snapshotProvider();
				} catch {
					metrics = null;
				}
			} catch (error) {
				log("error", `Resource preemption failed for ${victim.id}: ${error.message}`);
				break;
			}
		}
		syncMonitor();
	}

	function enqueue() {
		decisionTail = decisionTail
			.then(() => reconcile())
			.catch((error) => log("error", `Resource guard failed safely: ${error.message}`));
		return decisionTail;
	}

	async function handleRunEvent(event) {
		const conversationId = typeof event?.conversationId === "string" ? event.conversationId : "";
		if (!conversationId) return;
		const id = typeof event.clientId === "string" && event.clientId
			? 'localai-run:' + JSON.stringify([event.clientId, conversationId])
			: conversationId;
		if (event.type === "run_start") {
			if (!active.has(id)) active.set(id, { startedAt: Number(event.at) || Date.now(), conversationId, clientId: event.clientId });
			syncMonitor();
			return enqueue();
		}
		if (event.type === "run_end") {
			active.delete(id);
			syncMonitor();
		}
	}

	return {
		active,
		handleRunEvent,
		dispose() {
			if (monitor) clearInterval(monitor);
			monitor = null;
			active.clear();
		},
	};
}

function gib(bytes) {
	return `${(bytes / GIB).toFixed(1)} GiB`;
}

export default definePlugin({
	activate(host) {
		const manager = createCapacityManager(host);
		const offRun = host.onRunEvent((event) => manager.handleRunEvent(event));
		const offMessage = host.onMessage((payload) => {
			if (payload?.action !== "localai-resource-monitor:status") return;
			void readResourceSnapshot()
				.then((metrics) => {
					const canParallelize = hasConcurrencyHeadroom(metrics);
					const active = manager.active.size;
					const busy = Number.isFinite(metrics.gpuPeakEngineBusyPct)
						? `${metrics.gpuPeakEngineBusyPct.toFixed(0)}%`
						: "unavailable";
					host.notify(
						"info",
						`Compute: RAM free ${gib(metrics.ramAvailableBytes)}; RX 7900 XT GPU committed ${gib(metrics.gpuCommittedBytes)} / ${gib(metrics.gpuTotalBytes)}; peak GPU engine ${busy}; active Pi runs ${active}. ${canParallelize ? "Headroom allows up to two active runs." : "Safety policy permits one active run until headroom is sufficient."}`,
					);
				})
				.catch((error) => {
					host.notify("warning", `GPU counters unavailable: ${error.message}. Resource guard will limit Pi to one active run.`);
				});
		});
		host.log("info", "LocalAI compute guard activated (max two concurrent Pi runs, headroom-gated).");
		return () => {
			offRun?.();
			offMessage?.();
			manager.dispose();
			host.log("info", "LocalAI compute guard deactivated.");
		};
	},
});
