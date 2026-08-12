/**
 * specloop-pi mem bridge — thin orchestration around the `mem.py` CLI.
 *
 * Minimal two-touch model (see ../README.md): recall on the session's first
 * prompt, recap on session shutdown. The extension NEVER does HTTP — all
 * embedding + chat model work lives in the python engine (`engine.py` +
 * `semantic.py`), configured via env (default mistral). This module shells out,
 * parses JSON, formats a compact recall block, and builds the session digest
 * for the end-of-session recap. Degrades gracefully: first hard failure → the
 * caller disables recall for the rest of the session.
 *
 * One process per touch (→ one embedding on recall; one chat call on recap):
 *   start   recall similar past recaps            (before_agent_start, first prompt)
 *   recap   summarize the session into one node   (session_shutdown{quit}, background)
 */
import { spawn, spawnSync } from "node:child_process";
import { appendFileSync } from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

export type Config = {
	enabled: boolean;
	python: string;
	memPy: string;
	k: number;
	minScore: number; // recall inject threshold
	maxCharsM0: number; // token budget (approx, in chars)
	notify: boolean;
	audit: boolean;
	auditPath: string | null;
};

const TRUE = ["1", "true", "yes", "on"];
const OFF = ["0", "off", "false", "no"];
const bool = (v: string | undefined, d: boolean): boolean =>
	v === undefined ? d : TRUE.includes(v.toLowerCase());

export function defaultConfig(extDir: string): Config {
	const env = process.env;
	// mem.py lives at <repo>/lib/specloop-core/scripts/mem.py; extDir is
	// <repo>/extensions/specloop-pi/extension. Override with SPECLOOP_MEM when
	// installed elsewhere (e.g. as a pi package).
	const memPy =
		env.SPECLOOP_MEM ||
		path.resolve(extDir, "..", "..", "..", "lib", "specloop-core", "scripts", "mem.py");
	const auditRaw = env.SPECLOOP_AUDIT;
	const auditOff = auditRaw !== undefined && OFF.includes(auditRaw.toLowerCase());
	const auditPath = auditOff
		? null
		: auditRaw || path.join(os.homedir(), ".specloop", "audit.jsonl");
	return {
		enabled: bool(env.SPECLOOP_ENABLED, true),
		python: env.SPECLOOP_PYTHON || "python3",
		memPy,
		k: parseInt(env.SPECLOOP_K || "5", 10),
		minScore: parseFloat(env.SPECLOOP_MIN_SCORE || "0.4"),
		maxCharsM0: parseInt(env.SPECLOOP_MAX_CHARS_M0 || "2400", 10),
		notify: bool(env.SPECLOOP_NOTIFY, false),
		audit: auditPath !== null,
		auditPath,
	};
}

export class MemError extends Error {}

/** Low-level sync shell. Throws MemError on any failure. `opts.json` parses stdout. */
export function run(
	cfg: Config,
	args: string[],
	opts: { input?: string; json?: boolean; timeoutMs?: number; env?: Record<string, string> } = {},
): any {
	const full = opts.json ? [...args, "--json"] : args;
	const r = spawnSync(cfg.python, [cfg.memPy, ...full], {
		input: opts.input,
		env: { ...process.env, ...(opts.env || {}) },
		encoding: "utf8",
		timeout: opts.timeoutMs ?? 12000,
		maxBuffer: 8 * 1024 * 1024,
	});
	if (r.error) throw new MemError(`spawn failed: ${(r.error as Error).message}`);
	if (r.status !== 0) {
		const tail = (r.stderr || "").trim().split("\n").slice(-2).join(" ");
		throw new MemError(`mem ${args[0]} exit ${r.status}: ${tail}`);
	}
	const out = (r.stdout || "").trim();
	if (!opts.json) return out;
	if (!out) return null;
	try {
		return JSON.parse(out);
	} catch {
		throw new MemError(`mem ${args[0]}: unparseable json`);
	}
}

export type RecallHit = {
	id: string;
	type: string;
	body: string;
	project?: string;
	meta: Record<string, any>;
	_score?: number;
};

/** Env to thread the pi session id + audit path into every mem.py spawn. */
function sessionEnv(cfg: Config, session: string | null): Record<string, string> {
	const env: Record<string, string> = {};
	if (session) env.SPECLOOP_SESSION = session;
	if (cfg.auditPath) env.SPECLOOP_AUDIT = cfg.auditPath;
	return env;
}

/** Append one recall/lifecycle audit line (writes are logged by mem.py). */
export function appendAudit(cfg: Config, session: string | null, event: Record<string, any>): void {
	if (!cfg.audit || !cfg.auditPath) return;
	const line = {
		ts: Date.now() / 1000,
		session: session ?? null,
		project: process.env.SPECLOOP_PROJECT ?? null,
		...event,
	};
	try {
		appendFileSync(cfg.auditPath, JSON.stringify(line) + "\n");
	} catch {
		/* best-effort; auditing must never break the run */
	}
}

/** START (read): recall similar past recaps for this prompt. Throws on hard failure. */
export function start(
	cfg: Config,
	prompt: string,
	session: string | null = null,
): { recalls: RecallHit[] } {
	return run(cfg, ["start", prompt, "-k", String(cfg.k)], {
		env: sessionEnv(cfg, session),
		json: true,
		timeoutMs: 6000, // recall blocks before_agent_start — best-effort; a miss must not stall the run
	});
}

/** END (write): summarize the session into one recap node — fire-and-forget
 * background process (does the model call). Detached so it survives pi exiting
 * mid-write; unref()'d so it doesn't keep pi's event loop alive. */
export function recapAsync(
	cfg: Config,
	initialPrompt: string,
	digest: Digest,
	session: string | null = null,
): void {
	const child = spawn(
		cfg.python,
		[cfg.memPy, "recap", "--initial-prompt", initialPrompt],
		{
			stdio: ["pipe", "ignore", "ignore"],
			env: { ...process.env, ...sessionEnv(cfg, session) },
			detached: true,
		},
	);
	child.on("error", () => { /* best-effort; nothing captured mid-session to lose */ });
	child.stdin.write(JSON.stringify(digest));
	child.stdin.end();
	child.unref();
}

// ---- formatting / extraction (pure) ----
export function clip(s: string, n: number): string {
	s = (s || "").replace(/\s+/g, " ").trim();
	return s.length > n ? s.slice(0, Math.max(0, n - 1)) + "…" : s;
}

export function extractText(content: unknown): string {
	if (typeof content === "string") return content;
	if (!Array.isArray(content)) return "";
	return content
		.filter((b: any) => b && b.type === "text" && typeof b.text === "string")
		.map((b: any) => b.text)
		.join(" ");
}

/** Recall block for the system prompt (first prompt only). "" when no hits above
 * threshold → nothing is injected on quiet sessions. */
export function formatContext(cfg: Config, recalls: RecallHit[]): string {
	const hits = recalls.filter((r) => (r._score ?? 0) >= cfg.minScore && r.body).slice(0, 3);
	if (!hits.length) return "";
	const lines = ["## related past work (auto-recalled — consider but verify)"];
	let chars = 0;
	for (const r of hits) {
		const line = `- (${(r._score ?? 0).toFixed(2)}) ${clip(r.body, 220)}`;
		if (chars + line.length > cfg.maxCharsM0) break;
		lines.push(line);
		chars += line.length;
	}
	return lines.length > 1 ? lines.join("\n") : "";
}

// ---- session digest (built at shutdown from the entry tree) ----
export type Digest = { initial_prompt: string; prompts: string[]; errors: string[] };

/** Extract a compact session digest from `sessionManager.getEntries()`: the
 * initial prompt, the later user prompts (how the subject evolved), and the tool
 * errors. Best-effort + defensive — never throws (a parse miss just yields less
 * context for the recap model). Caps keep the payload small. */
export function buildDigest(entries: any[]): Digest {
	const prompts: string[] = [];
	const errors: string[] = [];
	for (const e of entries || []) {
		if (!e || e.type !== "message") continue;
		const m = e.message;
		if (!m || !m.role) continue;
		if (m.role === "user") {
			const t = clip(extractText(m.content), 240);
			if (t) prompts.push(t);
		} else if (m.role === "toolResult" && m.isError) {
			errors.push(`${m.toolName || "tool"}: ${clip(extractText(m.content), 200)}`);
		} else if (
			m.role === "bashExecution" && !m.cancelled &&
			m.exitCode !== undefined && m.exitCode !== 0
		) {
			errors.push(`bash(${m.exitCode}): ${clip(m.command || "", 120)}`);
		}
	}
	return {
		initial_prompt: prompts.length ? prompts[0] : "",
		prompts: prompts.slice(1, 21), // later prompts — the drift signal
		errors: errors.slice(0, 20),
	};
}
