/**
 * specloop-pi — the wired-in memory layer for pi.
 *
 * Minimal two-touch model (see ../README.md): ONE recall on the session's first
 * prompt, ONE recap when the session quits. Nothing per-turn, nothing per-error.
 *
 *   session_start        → health probe (no memory op); reset per-session state
 *   before_agent_start   → on the FIRST prompt only: recall similar past recaps,
 *                          show them as a checkable list (TUI picker; nothing
 *                          enters context yet) and insert ONLY the checked ones
 *                          as a persistent session message (visible once in the
 *                          transcript, in LLM context for the whole session)
 *   session_shutdown     → on reason "quit": build a digest from the session
 *                          transcript and write one recap node (background)
 *
 * Graceful degradation: the first hard mem failure disables recall for the
 * session (memory must never break the user's run). `/specloop off` disables
 * manually; `/specloop` shows status.
 *
 * The extension NEVER does HTTP. Embeddings AND the recap chat call both live
 * in the python engine (`engine.py` + `semantic.py`) behind `mem.py`; this
 * module only shells out, formats the recall block, builds the digest, and
 * injects/flushes.
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { fileURLToPath } from "node:url";
import * as path from "node:path";
import * as mem from "./mem.ts";
import { confirmGate } from "./picker.ts";

export default function specloopPi(pi: ExtensionAPI) {
	const extDir = path.dirname(fileURLToPath(import.meta.url));
	const cfg = mem.defaultConfig(extDir);

	let memOk = true; // flipped off on first hard failure (one notify)
	let recalledThisSession = false; // gate: recall once per session
	let firstPrompt: string | null = null; // session subject anchor, reused at recap
	let sessionId: string | null = null;

	const disable = (msg: string, ctx?: any) => {
		if (!memOk) return;
		memOk = false;
		mem.appendAudit(cfg, sessionId, { event: "lifecycle", state: "disabled", reason: msg });
		if (cfg.notify && ctx?.ui) ctx.ui.notify(`specloop disabled: ${msg}`, "warning");
	};

	// ---- session: cheap probe (python3 + mem.py path + db). Key check is lazy
	// (caught on first `start`). Reset per-session recall state here — every
	// session_start (startup/new/resume/fork/reload) recalls once again.
	// The probe runs on EVERY start, even after a previous disable: a transient
	// failure (e.g. reading a file mid-rewrite) must not latch memory off for
	// the whole process lifetime — if the probe now passes, we re-enable.
	// ------------------------------------------------------------------------
	pi.on("session_start", async (_event, ctx) => {
		recalledThisSession = false;
		firstPrompt = null;
		if (!cfg.enabled) return;
		sessionId = (ctx as any)?.sessionManager?.getSessionId?.() ?? null;
		// stamp every audit line + mem.py spawn with the project scope key
		// (same rule as mem.py's detect_project — git toplevel basename)
		if (!process.env.SPECLOOP_PROJECT) process.env.SPECLOOP_PROJECT = mem.detectProject();
		try {
			mem.run(cfg, ["stats"], { json: true, timeoutMs: 8000 });
		} catch (err) {
			disable(String((err as Error).message || err), ctx);
			return;
		}
		const wasDisabled = !memOk;
		memOk = true;
		mem.appendAudit(cfg, sessionId, {
			event: "lifecycle", state: "enabled",
			...(wasDisabled ? { recovered: true } : {}),
		});
		if (wasDisabled && cfg.notify && ctx?.ui) {
			ctx.ui.notify("specloop: recovered (previous probe failure was transient)", "info");
		}
		// crash-safety: re-run recaps whose process died (reboot, killed pi)
		try { mem.recoverSpooledRecaps(cfg); } catch { /* best-effort */ }
	});

	// ---- compact transcript rendering of an inserted recall block ----------
	// The injected message is displayed ONCE, at its position (right after the
	// first prompt) — it never re-renders on later messages. Collapsed: one
	// summary line; expanded: the exact text the LLM sees.
	pi.registerMessageRenderer("specloop-recall", (message: any, options: any, theme: any) => {
		const { expanded, outputPad } = options ?? {};
		const details = (message.details ?? {}) as { scores?: number[] };
		const scores = details.scores ?? [];
		const n = scores.length;
		let head = theme.fg("accent", `specloop: ${n} related memor${n === 1 ? "y" : "ies"} inserted`);
		if (n) head += theme.fg("dim", ` (${scores.map((s) => s.toFixed(2)).join(", ")})`);
		if (!expanded) head += theme.fg("dim", " · expand for full text");
		const lines = [head];
		if (expanded) {
			for (const l of String(message.content ?? "").split("\n")) {
				lines.push(theme.fg("muted", l));
			}
		}
		return new Text(lines.join("\n"), outputPad ?? 1, 0);
	});

	// ---- START (read): recall on the FIRST prompt, insert what the user checks -
	// Nothing is loaded into LLM context before validation: the picker renders
	// in the terminal only, and the injection happens solely through this
	// handler's return value (built from the checked subset). Esc → insert
	// nothing (and don't re-ask this session).
	pi.on("before_agent_start", async (event, ctx) => {
		if (!cfg.enabled || !memOk || recalledThisSession) return;
		const prompt = (event.prompt || "").trim();
		if (prompt.length < 4) return;

		let recalls: mem.RecallHit[];
		try {
			recalls = mem.start(cfg, prompt, sessionId).recalls || [];
		} catch (err) {
			disable(String((err as Error).message || err), ctx);
			return;
		}
		recalledThisSession = true;
		firstPrompt = prompt;

		const aboveMin = recalls.filter((r) => (r._score ?? 0) >= cfg.minScore && r.body);
		const hits = aboveMin.slice(0, 3);
		if (!hits.length) {
			mem.appendAudit(cfg, sessionId, {
				event: "recall", phase: "start", query: prompt,
				k: cfg.k, above: 0, mode: cfg.confirm, cancelled: false,
				hits: [], injected: false, chars: 0, vehicle: "message",
			});
			return; // nothing relevant → nothing to validate or insert
		}

		// ---- validation gate ("no magic") ----
		let chosen = hits;
		let gateMode: string = cfg.confirm;
		let cancelled = false;
		if (cfg.confirm === "ask") {
			const gate = await confirmGate(ctx as any, hits, cfg.pickTimeoutMs);
			chosen = gate.chosen;
			gateMode = gate.mode;
			cancelled = gate.cancelled;
		}

		const block = chosen.length ? mem.formatContext(cfg, chosen) : "";
		const accepted = new Set(chosen);
		mem.appendAudit(cfg, sessionId, {
			event: "recall", phase: "start", query: prompt,
			k: cfg.k, above: aboveMin.length, mode: gateMode, cancelled,
			hits: hits.map((r) => ({ id: r.id, score: +(r._score ?? 0).toFixed(2), accepted: accepted.has(r) })),
			injected: !!block, chars: block.length, vehicle: "message",
		});
		if (!block) {
			if (cfg.notify) ctx.ui.notify(`specloop: no memories inserted${cancelled ? " (skipped)" : ""}`, "info");
			return;
		}
		if (cfg.notify) ctx.ui.notify(`specloop: inserted ${chosen.length}/${hits.length} recalled`, "info");
		return {
			message: {
				customType: "specloop-recall",
				content: block,
				display: true,
				details: {
					scores: chosen.map((r) => +(r._score ?? 0).toFixed(2)),
					ids: chosen.map((r) => r.id),
				},
			},
		};
	});

	// ---- END (write): one recap when the session quits -----------------------
	pi.on("session_shutdown", async (event, ctx) => {
		if (!cfg.enabled || !memOk) return;
		const reason = (event as any)?.reason ?? "unknown";
		if (reason !== "quit") {
			// reload/new/resume/fork deliberately skip the recap — but say so in
			// the audit (coverage was previously unverifiable for these sessions)
			if (firstPrompt) {
				mem.appendAudit(cfg, sessionId, { event: "lifecycle", state: "shutdown_skipped", reason });
			}
			return;
		}
		if (!firstPrompt) return; // nothing was recalled → nothing to recap

		const sm = (ctx as any)?.sessionManager;
		const entries = typeof sm?.getEntries === "function" ? sm.getEntries() : [];
		const digest = mem.buildDigest(entries);
		// prefer the transcript's true first prompt if we can see it
		const initialPrompt = digest.initial_prompt || firstPrompt;

		mem.appendAudit(cfg, sessionId, {
			event: "lifecycle", state: "recap_queued",
			prompts: digest.prompts.length, total_prompts: digest.total_prompts,
			errors: digest.errors.length,
		});
		try {
			const spool = mem.recapAsync(cfg, initialPrompt, digest, sessionId);
			// distinguish "spawned" from "completed" — a queued+spawned recap
			// with no write events afterwards is now diagnosable (spool/audit)
			mem.appendAudit(cfg, sessionId, {
				event: "lifecycle", state: "recap_spawned",
				spool: spool ? path.basename(spool) : null,
			});
			if (cfg.notify) ctx.ui.notify("specloop: saving session recap…", "info");
		} catch {
			/* best-effort; fire-and-forget */
		}
	});

	// ---- /specloop manual command ------------------------------------------
	pi.registerCommand("specloop", {
		description: "specloop memory: recall <query> | pick [query] | stats | off",
		handler: async (args, ctx) => {
			const [sub, ...rest] = (args || "").trim().split(/\s+/);
			try {
				if (sub === "off") {
					memOk = false;
					ctx.ui.notify("specloop: disabled for this session", "info");
				} else if (sub === "stats") {
					const s = mem.run(cfg, ["stats"], { json: true });
					ctx.ui.notify(`specloop stats: ${JSON.stringify(s)}`, "info");
				} else if (sub === "recall") {
					const q = rest.join(" ").trim();
					if (!q) return ctx.ui.notify("usage: /specloop recall <query>", "info");
					const r: mem.RecallHit[] = mem.run(cfg, ["recall", q, "-k", String(cfg.k)], {
						json: true,
					});
					const lines = (r || [])
						.map((h) => `${(h._score ?? 0).toFixed(2)} ${mem.clip(h.body, 70)}`);
					ctx.ui.notify(
						lines.length ? `specloop recall:\n${lines.join("\n")}` : "specloop recall: (none)",
						"info",
					);
				} else if (sub === "pick") {
					// manual recall + validation gate + insert (no model turn triggered)
					const q = rest.join(" ").trim() || firstPrompt;
					if (!q) {
						return ctx.ui.notify("usage: /specloop pick [query] (defaults to the session's first prompt)", "info");
					}
					if (!cfg.enabled || !memOk) return ctx.ui.notify("specloop is disabled", "warning");
					const r: mem.RecallHit[] = mem.run(cfg, ["recall", q, "-k", String(cfg.k)], {
						json: true,
						timeoutMs: cfg.recallTimeoutMs,
					});
					const hits = (r || [])
						.filter((h) => (h._score ?? 0) >= cfg.minScore && h.body)
						.slice(0, 3);
					if (!hits.length) return ctx.ui.notify("specloop pick: no related memories", "info");
					const gate = await confirmGate(ctx as any, hits, cfg.pickTimeoutMs);
					const block = gate.chosen.length ? mem.formatContext(cfg, gate.chosen) : "";
					mem.appendAudit(cfg, sessionId, {
						event: "recall", phase: "pick", query: q, mode: gate.mode, cancelled: gate.cancelled,
						hits: hits.map((h) => ({
							id: h.id, score: +(h._score ?? 0).toFixed(2), accepted: gate.chosen.includes(h),
						})),
						injected: !!block, chars: block.length, vehicle: "message",
					});
					if (!block) return ctx.ui.notify("specloop pick: nothing inserted", "info");
					pi.sendMessage({
						customType: "specloop-recall",
						content: block,
						display: true,
						details: {
							scores: gate.chosen.map((h) => +(h._score ?? 0).toFixed(2)),
							ids: gate.chosen.map((h) => h.id),
						},
					}, { triggerTurn: false }); // idle → appended to the session, no turn
				} else {
					const shortMem = cfg.memPy.split("/").slice(-2).join("/");
					ctx.ui.notify(
						`specloop ${memOk ? "ON" : "OFF"} · k=${cfg.k} · minScore=${cfg.minScore} · mem=${shortMem}`,
						"info",
					);
				}
			} catch (e) {
				ctx.ui.notify(
					`specloop error: ${mem.clip(String((e as Error).message || e), 120)}`,
					"warning",
				);
			}
		},
	});
}
