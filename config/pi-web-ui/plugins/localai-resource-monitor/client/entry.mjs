/**
 * localai-resource-monitor —— 客户端视图（pi-web-ui plugin create --template ui-slot 生成）。
 * 约定：服务端 ESM 默认导出 { activate(host) → cleanup? }；
 * 客户端 ESM 默认导出 { mount(container, ctx) → cleanup? }。
 */
import { defineView, onUiAction } from "./sdk/index.mjs";

export default defineView({
	mount(container, ctx) {
		const el = document.createElement("div");
		el.style.padding = "16px";
		el.textContent = "Pi inference concurrency is limited by measured Windows RAM and RX 7900 XT headroom. Use the composer action to inspect current capacity.";
		container.appendChild(el);
		const off = onUiAction("localai-resource-monitor:status", () => {
			el.textContent = "Checking Windows memory and GPU counters…";
			ctx.send({ action: "localai-resource-monitor:status" });
		});
		return () => {
			off();
			el.remove();
		};
	},
});
