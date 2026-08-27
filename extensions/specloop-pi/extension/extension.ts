/**
 * specloop-pi — the wired-in memory layer for pi.
 *
 * Minimal two-touch model (see ../README.md): ONE recall on the session's first
 * prompt, ONE recap when the session quits. Nothing per-turn, nothing per-error.
 *
 *   session_start        → health probe (no memory op); reset per-session state
 *   before_agent_start   → on the FIRST prompt only: recall similar past recaps
 *                          and inject them into the system prompt (read-only)
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
import { fileURLToPath } from "node:url";
import * as path from "node:path";
import * as mem from "./mem.ts";

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

	// ---- START (read): recall similar past recaps on the FIRST prompt only ----
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

		const block = mem.formatContext(cfg, recalls);
		const aboveMin = recalls.filter((r) => (r._score ?? 0) >= cfg.minScore);
		const hits = aboveMin.slice(0, 3);
		mem.appendAudit(cfg, sessionId, {
			event: "recall", phase: "start", query: prompt,
			k: cfg.k, above: aboveMin.length, // pre-slice signal (was hidden before)
			hits: hits.map((r) => ({ id: r.id, score: +(r._score ?? 0).toFixed(2) })),
			injected: !!block, chars: block.length,
		});
		if (!block) return; // nothing relevant → inject nothing
		if (cfg.notify && hits.length) ctx.ui.notify(`specloop: recalled ${hits.length} related`, "info");
		return { systemPrompt: `${event.systemPrompt}\n${block}` };
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
		description: "specloop memory: recall <query> | stats | off",
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
