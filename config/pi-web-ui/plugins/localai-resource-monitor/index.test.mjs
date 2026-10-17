import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createCapacityManager, hasConcurrencyHeadroom, selectOldestRun } from "./index.mjs";

const GIB = 1024 ** 3;
const safe = { ramAvailableBytes: 16 * GIB, gpuFreeBytes: 10 * GIB, gpuPeakEngineBusyPct: 30 };

describe("LocalAI compute guard", () => {
	it("tracks identical conversation IDs from different browser clients separately", async () => {
		const aborted=[];
		const manager=createCapacityManager({abortRun:async id=>(aborted.push(id),{ok:true}),notify(){},log(){}},{snapshotProvider:async()=>null});
		await manager.handleRunEvent({type:'run_start',clientId:'phone',conversationId:'c1',at:1});
		await manager.handleRunEvent({type:'run_start',clientId:'desktop',conversationId:'c1',at:2});
		assert.deepEqual(aborted,['localai-run:["phone","c1"]']);
		assert.deepEqual([...manager.active.keys()],['localai-run:["desktop","c1"]']);
		await manager.handleRunEvent({type:'run_end',clientId:'phone',conversationId:'c1'});
		assert.equal(manager.active.size,1);
		manager.dispose();
	});
	it("never reports a rejected interrupt as a successful pause", async () => {
		const notices=[];
		const manager=createCapacityManager({abortRun:async()=>({ok:false,error:'explicit refusal'}),notify:(...args)=>notices.push(args),log(){}},{snapshotProvider:async()=>null});
		await manager.handleRunEvent({type:'run_start',clientId:'phone',conversationId:'c1',at:1});
		await manager.handleRunEvent({type:'run_start',clientId:'desktop',conversationId:'c2',at:2});
		assert.equal(manager.active.size,2);
		assert.equal(notices.length,1);
		assert.match(notices[0][1],/explicit refusal/);
		await manager.handleRunEvent({type:'run_start',clientId:'third',conversationId:'c3',at:3});
		assert.equal(notices.length,1,'Do not spam the same rejected interruption');
		manager.dispose();
	});
	it("allows a second run only when RAM, VRAM, and GPU load all have headroom", () => {
		assert.equal(hasConcurrencyHeadroom(safe), true);
		assert.equal(hasConcurrencyHeadroom({ ...safe, ramAvailableBytes: 11 * GIB }), false);
		assert.equal(hasConcurrencyHeadroom({ ...safe, gpuFreeBytes: 5 * GIB }), false);
		assert.equal(hasConcurrencyHeadroom({ ...safe, gpuPeakEngineBusyPct: 90 }), false);
		assert.equal(hasConcurrencyHeadroom(null), false);
	});

	it("selects the oldest run for preemption", () => {
		const active = new Map([
			["later", { startedAt: 200 }],
			["earlier", { startedAt: 100 }],
		]);
		assert.equal(selectOldestRun(active).id, "earlier");
	});

	it("keeps both runs when telemetry shows headroom", async () => {
		const aborted = [];
		const manager = createCapacityManager(
			{
				abortRun: async (id) => (aborted.push(id), { ok: true }),
				notify() {},
				log() {},
			},
			{ snapshotProvider: async () => safe },
		);
		await manager.handleRunEvent({ type: "run_start", conversationId: "one", at: 1 });
		await manager.handleRunEvent({ type: "run_start", conversationId: "two", at: 2 });
		assert.deepEqual(aborted, []);
		manager.dispose();
	});

	it("interrupts the oldest run at capacity without removing the newer session", async () => {
		const aborted = [];
		const manager = createCapacityManager(
			{
				abortRun: async (id) => (aborted.push(id), { ok: true }),
				notify() {},
				log() {},
			},
			{ snapshotProvider: async () => ({ ...safe, gpuFreeBytes: 3 * GIB }) },
		);
		await manager.handleRunEvent({ type: "run_start", conversationId: "older", at: 1 });
		await manager.handleRunEvent({ type: "run_start", conversationId: "newer", at: 2 });
		assert.deepEqual(aborted, ["older"]);
		assert.deepEqual([...manager.active.keys()], ["newer"]);
		manager.dispose();
	});
});
