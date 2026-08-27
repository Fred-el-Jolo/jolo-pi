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
import { appendFileSync, closeSync, mkdirSync, openSync, readFileSync, readdirSync, statSync, unlinkSync, writeFileSync } from "node:fs";
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

/** Project scope key for audit lines + mem.py spawns (same rule as mem.py's
 * detect_project: git toplevel basename, else cwd basename). Set once per
 * session by the extension so audit "project" stops being null everywhere. */
export function detectProject(): string {
	try {
		const r = spawnSync("git", ["rev-parse", "--show-toplevel"], {
			encoding: "utf8",
			timeout: 3000,
		});
		if (r.status === 0 && (r.stdout || "").trim()) {
			return path.basename(r.stdout.trim());
		}
	} catch {
		/* not a git repo / git missing → cwd basename */
	}
	return path.basename(process.cwd());
}

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

/** State dir that holds the audit log (spool/ + recap-errors.log live there
 * too — durability is orthogonal to auditing, so it is derived even when the
 * audit log itself is disabled). */
export function stateDir(cfg: Config): string {
	return path.dirname(cfg.auditPath || path.join(os.homedir(), ".specloop", "audit.jsonl"));
}

/** A spooled recap younger than this is assumed in-flight (another pi may be
 * writing it right now); older ones are crash leftovers → recover them. */
export const SPOOL_GRACE_MS = 5 * 60_000;

/** END (write): summarize the session into one recap node — fire-and-forget
 * background process (does the model call). Detached so it survives pi exiting
 * mid-write; unref()'d so it doesn't keep pi's event loop alive.
 *
 * Crash-safety: before spawning, the exact recap payload is spooled to
 * `<stateDir>/spool/<session>-<ts>.json` and passed via `--spool-file` — mem.py
 * unlinks it on ANY exit path, so a leftover file means the process died
 * (killed pi, reboot) and the next session_start re-runs it. The child's stderr
 * is appended to `<stateDir>/recap-errors.log` (it was silently discarded
 * before — lost recaps were undiagnosable). Returns the spool path (or null). */
export function recapAsync(
	cfg: Config,
	initialPrompt: string,
	digest: Digest,
	session: string | null = null,
): string | null {
	const spoolDir = path.join(stateDir(cfg), "spool");
	let spoolPath: string | null = null;
	try {
		mkdirSync(spoolDir, { recursive: true });
		spoolPath = path.join(spoolDir, `${session || "unknown"}-${Date.now()}.json`);
		writeFileSync(spoolPath, JSON.stringify({
			session,
			project: process.env.SPECLOOP_PROJECT ?? null,
			initial_prompt: initialPrompt,
			digest,
			queued_at: Date.now(),
		}));
	} catch {
		spoolPath = null; // durability is best-effort; the recap itself still runs
	}
	let errFd: number | undefined;
	try {
		errFd = openSync(path.join(stateDir(cfg), "recap-errors.log"), "a");
		appendFileSync(errFd, `[${new Date().toISOString()} ${session || "-"}] recap ${clip(initialPrompt, 60)}\n`);
	} catch {
		errFd = undefined;
	}
	const args = [cfg.memPy, "recap", "--initial-prompt", initialPrompt];
	if (spoolPath) args.push("--spool-file", spoolPath);
	const child = spawn(cfg.python, args, {
		stdio: ["pipe", "ignore", errFd !== undefined ? errFd : "ignore"],
		env: { ...process.env, ...sessionEnv(cfg, session) },
		detached: true,
	});
	child.on("error", () => { /* best-effort; the spool file makes it recoverable */ });
	child.stdin?.write(JSON.stringify(digest));
	child.stdin?.end();
	child.unref();
	if (errFd !== undefined) {
		try { closeSync(errFd); } catch { /* already closed */ }
	}
	return spoolPath;
}

/** Re-run recaps whose mem.py process died before completing (spool file older
 * than SPOOL_GRACE_MS). Each recovery spawns a fresh recap (with its own new
 * spool) and removes the old file. Returns how many were recovered. */
export function recoverSpooledRecaps(cfg: Config): number {
	const spoolDir = path.join(stateDir(cfg), "spool");
	let files: string[];
	try {
		files = readdirSync(spoolDir).filter((f) => f.endsWith(".json"));
	} catch {
		return 0; // no spool dir yet → nothing to recover
	}
	const cutoff = Date.now() - SPOOL_GRACE_MS;
	let recovered = 0;
	for (const f of files) {
		const p = path.join(spoolDir, f);
		try {
			if (statSync(p).mtimeMs > cutoff) continue; // likely in-flight right now
			const data = JSON.parse(readFileSync(p, "utf8"));
			recapAsync(
				cfg,
				String(data.initial_prompt || "(recovered recap)"),
				data.digest || { initial_prompt: "", prompts: [], errors: [], total_prompts: 0 },
				data.session ?? null,
			);
			unlinkSync(p);
			recovered++;
			appendAudit(cfg, data.session ?? null, { event: "lifecycle", state: "recap_recovered", file: f });
		} catch {
			/* one bad spool file must not block the others */
		}
	}
	return recovered;
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
export type Digest = {
	initial_prompt: string;
	prompts: string[]; // later prompts only (the drift signal)
	errors: string[];
	total_prompts: number; // ALL user prompts incl. the first (audit/observability)
};

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
		total_prompts: prompts.length,
	};
}
