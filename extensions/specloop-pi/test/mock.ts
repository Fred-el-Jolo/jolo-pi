/**
 * Mock-pi smoke test for the specloop validation gate.
 * Drives the REAL extension + REAL picker component through a fake pi API
 * (no TUI needed — the picker component is fed key sequences directly).
 *
 * Run: node extensions/specloop-pi/test/mock.ts
 *
 * Node's TS type-stripping can't resolve "@earendil-works/pi-tui" (no
 * node_modules in this repo), so this script creates a temporary symlink
 * <repo>/node_modules/@earendil-works/pi-tui -> the globally installed one and
 * removes it on exit (pi itself loads the extension via jiti, which resolves
 * against its own node_modules).
 */
import { existsSync, mkdirSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { spawnSync } from "node:child_process";

// ---- temporary pi-tui resolver symlink (created/cleaned by this test) -------
const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..", "..", "..");
const linkPath = path.join(repoRoot, "node_modules", "@earendil-works", "pi-tui");
{
	const npmRoot = spawnSync("npm", ["root", "-g"], { encoding: "utf8" }).stdout?.trim();
	const target = npmRoot && path.join(npmRoot, "@earendil-works", "pi-coding-agent", "node_modules", "@earendil-works", "pi-tui");
	if (target && existsSync(target) && !existsSync(linkPath)) {
		mkdirSync(path.dirname(linkPath), { recursive: true });
		symlinkSync(target, linkPath);
		process.on("exit", () => { try { rmSync(path.join(repoRoot, "node_modules"), { recursive: true, force: true }); } catch {} });
	}
}

const tmp = mktmp();
process.env.SPECLOOP_MEM = path.join(tmp, "stub-mem.py");
process.env.SPECLOOP_AUDIT = path.join(tmp, "audit.jsonl");
process.env.STUB_CALLS = path.join(tmp, "calls.log");
writeFileSync(process.env.SPECLOOP_MEM, readFileSync(new URL("./stub-mem.py", import.meta.url), "utf8"));

const EXT = new URL("../extension/extension.ts", import.meta.url).pathname;
const PICKER = new URL("../extension/picker.ts", import.meta.url).pathname;

const theme = { fg: (_c: string, s: string) => s, bold: (s: string) => s };
const tui = { requestRender: () => {} };
const KEYS = { esc: "\x1b", enter: "\r", space: " ", up: "\x1b[A", down: "\x1b[B" };

function mktmp(): string {
	const d = path.join(os.tmpdir(), `specloop-mock-${Date.now()}`);
	mkdirSync(d, { recursive: true });
	return d;
}

function auditLines(): any[] {
	if (!existsSync(process.env.SPECLOOP_AUDIT!)) return [];
	return readFileSync(process.env.SPECLOOP_AUDIT!, "utf8").trim().split("\n").filter(Boolean).map((l) => JSON.parse(l));
}
function stubCalls(): string[] {
	if (!existsSync(process.env.STUB_CALLS!)) return [];
	return readFileSync(process.env.STUB_CALLS!, "utf8").trim().split("\n").filter(Boolean);
}
function resetCaptures() {
	for (const p of [process.env.SPECLOOP_AUDIT!, process.env.STUB_CALLS!]) {
		if (existsSync(p)) rmSync(p);
	}
}

/** Fresh pi capture harness. */
function freshPi() {
	const handlers: Record<string, any[]> = {};
	const commands: Record<string, any> = {};
	const renderers: Record<string, any> = {};
	const sent: any[] = [];
	const harness = { handlers, commands, renderers, sent, pi: null as any };
	harness.pi = {
		on: (ev: string, h: any) => ((handlers[ev] ??= []).push(h)),
		registerCommand: (name: string, def: any) => (commands[name] = def),
		registerMessageRenderer: (t: string, r: any) => (renderers[t] = r),
		sendMessage: (m: any, o: any) => { sent.push({ m, o }); return Promise.resolve(); },
	};
	return harness;
}

/** Build a mock ExtensionContext with a scriptable picker/confirm. */
function makeCtx(opts: {
	mode?: string; hasUI?: boolean;
	keys?: string[];             // keys fed to the picker component
	customThrows?: boolean;      // simulate a broken custom()
	confirmResult?: boolean;     // scripted confirm() result (rpc path)
} = {}) {
	const notes: string[] = [];
	let customCalls = 0;
	const ctx: any = {
		mode: opts.mode ?? "tui",
		hasUI: opts.hasUI ?? (opts.mode !== "print" && opts.mode !== "json"),
		ui: {
			custom: async (factory: any) => {
				customCalls++;
				if (opts.customThrows) throw new Error("boom");
				return new Promise((resolve) => {
					const comp = factory(tui, theme, {}, (v: any) => resolve(v));
					for (const k of opts.keys ?? []) comp.handleInput(k);
				});
			},
			confirm: async (_t: string, _m: string) => opts.confirmResult ?? true,
			notify: (m: string, _lvl?: string) => notes.push(m),
		},
		sessionManager: {
			getSessionId: () => "s-mock",
			getEntries: () => [
				{ type: "message", message: { role: "user", content: [{ type: "text", text: "first prompt about extension testing" }] } },
				{ type: "message", message: { role: "user", content: [{ type: "text", text: "second prompt" }] } },
			],
		},
	};
	(ctx as any).__notes = notes;
	(ctx as any).__customCalls = () => customCalls;
	return ctx;
}

async function fire(h: any[], ev: string, event: any, ctx: any) {
	let last: any;
	for (const fn of h ?? []) last = await fn(event, ctx);
	return last;
}

const results: string[] = [];
const ok = (name: string, cond: boolean, extra?: string) => {
	results.push(`${cond ? "PASS" : "FAIL"}  ${name}${extra && !cond ? ` — ${extra}` : ""}`);
	if (!cond) process.exitCode = 1;
};

// ---------------------------------------------------------------- scenarios
const { default: specloopPi } = await import(EXT);
const pickerMod = await import(PICKER);

// --- unit: splitLesson + component render/keys -----------------------------
{
	const s = pickerMod.splitLesson("WHEN pi extension tests hang THEN drive logic through a mock pi");
	ok("splitLesson splits WHEN/THEN", s.when.startsWith("WHEN pi extension") && s.then.startsWith("THEN drive"));
	const b = pickerMod.splitLesson("just a plain body");
	ok("splitLesson plain body", b.when === "just a plain body" && b.then === "");

	const hits = [
		{ id: "n1", type: "lesson", body: "WHEN a THEN b", meta: {}, _score: 0.9 },
		{ id: "n2", type: "lesson", body: "WHEN c THEN d", meta: {}, _score: 0.7 },
	];
	let outcome: any = null;
	const comp = new pickerMod.RecallPickerComponent(hits, theme, (o: any) => (outcome = o), () => {}, 0);
	const lines = comp.render(80);
	ok("render: 2 items, all pre-checked", lines.join("\n").includes("[x]") && lines.filter((l: string) => l.includes("[x]")).length === 2);
	ok("render: every line within width", lines.every((l: string) => stripAnsiLen(l) <= 80));
	comp.handleInput(KEYS.space);      // uncheck first
	comp.handleInput(KEYS.down);
	comp.handleInput(KEYS.enter);      // confirm
	ok("component: space+enter → chosen = unchecked-out subset", outcome?.kind === "confirm" && outcome.chosen.length === 1 && outcome.chosen[0].id === "n2");
	const comp2 = new pickerMod.RecallPickerComponent(hits, theme, (o: any) => (outcome = o), () => {}, 0);
	comp2.handleInput(KEYS.esc);
	ok("component: esc → cancel", outcome?.kind === "cancel");
	const comp3 = new pickerMod.RecallPickerComponent(hits, theme, (o: any) => (outcome = o), () => {}, 0);
	comp3.handleInput("a");           // all→none
	ok("component: 'a' toggles all off", comp3.render(80).join("\n").includes("[ ]"));
}

function stripAnsiLen(s: string): number {
	return s.replace(/\x1b\[[0-9;]*m/g, "").length;
}

// --- scenario A: ask mode, user unchecks the middle hit, confirms ----------
{
	resetCaptures();
	const h = freshPi();
	specloopPi(h.pi as any);
	const ctx = makeCtx({ keys: [KEYS.down, KEYS.space, KEYS.enter] });
	await fire(h.handlers.session_start, "session_start", { reason: "startup" }, ctx);
	const ret = await fire(h.handlers.before_agent_start, "before_agent_start",
		{ prompt: "how do I test my pi extension?", systemPrompt: "BASE" }, ctx);
	ok("A: returns a message (not systemPrompt)", !!ret?.message && !ret?.systemPrompt);
	const content = ret?.message?.content ?? "";
	ok("A: content has checked n1+n3, not unchecked n2",
		content.includes("mock pi") && content.includes("dimGray") && !content.includes("dedup"));
	ok("A: customType + display", ret.message.customType === "specloop-recall" && ret.message.display === true);
	const ev = auditLines().filter((l) => l.event === "recall").pop();
	ok("A: audit mode=picker, per-hit accepted flags",
		ev?.mode === "picker" && ev.hits.length === 3 && ev.hits[0].accepted === true && ev.hits[1].accepted === false && ev.hits[2].accepted === true);
	ok("A: audit vehicle=message injected=true", ev?.vehicle === "message" && ev?.injected === true && !ev?.cancelled);

	// second prompt → once-per-session gate (no second start spawn)
	await fire(h.handlers.before_agent_start, "before_agent_start", { prompt: "another prompt entirely", systemPrompt: "BASE" }, ctx);
	ok("A: once-per-session gate (one start spawn)", stubCalls().filter((c) => c === "start").length === 1);

	// renderer registered and compact
	const r = h.renderers["specloop-recall"];
	ok("A: message renderer registered", typeof r === "function");
	const text = r({ content, details: { scores: [0.9, 0.55] } }, { expanded: false }, theme);
	const rendered = text.render ? text.render(100).join("\n") : "";
	ok("A: renderer collapsed line is compact + score summary", rendered.includes("2 related memories inserted") && rendered.includes("0.90") && !rendered.includes("## related"));
}

// --- scenario B: esc → insert nothing, audited as cancelled ---------------
{
	resetCaptures();
	const h = freshPi();
	specloopPi(h.pi as any);
	const ctx = makeCtx({ keys: [KEYS.esc] });
	await fire(h.handlers.session_start, "session_start", { reason: "startup" }, ctx);
	const ret = await fire(h.handlers.before_agent_start, "before_agent_start", { prompt: "query for esc path", systemPrompt: "BASE" }, ctx);
	ok("B: esc → no return (nothing inserted)", ret === undefined);
	const ev = auditLines().filter((l) => l.event === "recall").pop();
	ok("B: audit cancelled=true injected=false all accepted=false",
		ev?.cancelled === true && ev?.injected === false && ev.hits.every((x: any) => !x.accepted));
}

// --- scenario C: SPECLOOP_CONFIRM=auto → no picker, all inserted -----------
{
	resetCaptures();
	process.env.SPECLOOP_CONFIRM = "auto";
	const h = freshPi();
	specloopPi(h.pi as any);
	const ctx = makeCtx({ keys: [KEYS.enter] });
	await fire(h.handlers.session_start, "session_start", { reason: "startup" }, ctx);
	const ret = await fire(h.handlers.before_agent_start, "before_agent_start", { prompt: "auto mode query", systemPrompt: "BASE" }, ctx);
	ok("C: auto → message with all 3 hits", (ret?.message?.content.match(/- \(/g) || []).length === 3);
	ok("C: picker never shown", ctx.__customCalls() === 0);
	const ev = auditLines().filter((l) => l.event === "recall").pop();
	ok("C: audit mode=auto", ev?.mode === "auto");
	delete process.env.SPECLOOP_CONFIRM;
}

// --- scenario D: picker throws → fail open (all hits, picker_error) --------
{
	resetCaptures();
	const h = freshPi();
	specloopPi(h.pi as any);
	const ctx = makeCtx({ customThrows: true });
	await fire(h.handlers.session_start, "session_start", { reason: "startup" }, ctx);
	const ret = await fire(h.handlers.before_agent_start, "before_agent_start", { prompt: "broken picker query", systemPrompt: "BASE" }, ctx);
	ok("D: picker_error → fail open, all 3 inserted", (ret?.message?.content.match(/- \(/g) || []).length === 3);
	const ev = auditLines().filter((l) => l.event === "recall").pop();
	ok("D: audit mode=picker_error", ev?.mode === "picker_error");
}

// --- scenario E: rpc mode → confirm() fallback ------------------------------
{
	resetCaptures();
	const h = freshPi();
	specloopPi(h.pi as any);
	for (const [confirmRes, want] of [[false, 0], [true, 3]] as const) {
		const ctx = makeCtx({ mode: "rpc", confirmResult: confirmRes });
		await fire(h.handlers.session_start, "session_start", { reason: "startup" }, ctx);
		const ret = await fire(h.handlers.before_agent_start, "before_agent_start", { prompt: "rpc mode query", systemPrompt: "BASE" }, ctx);
		const n = (ret?.message?.content.match(/- \(/g) || []).length;
		ok(`E: rpc confirm=${confirmRes} → ${want} inserted`, n === want && ctx.__customCalls() === 0);
		const ev = auditLines().filter((l) => l.event === "recall").pop();
		ok(`E: rpc audit mode=rpc_confirm cancelled=${!confirmRes}`, ev?.mode === "rpc_confirm" && ev?.cancelled === !confirmRes);
		resetCaptures();
	}
}

// --- scenario F: print mode (no UI) → auto_no_ui ----------------------------
{
	resetCaptures();
	const h = freshPi();
	specloopPi(h.pi as any);
	const ctx = makeCtx({ mode: "print", hasUI: false });
	await fire(h.handlers.session_start, "session_start", { reason: "startup" }, ctx);
	const ret = await fire(h.handlers.before_agent_start, "before_agent_start", { prompt: "print mode query", systemPrompt: "BASE" }, ctx);
	ok("F: print → all 3 inserted", (ret?.message?.content.match(/- \(/g) || []).length === 3);
	ok("F: audit mode=auto_no_ui", auditLines().filter((l) => l.event === "recall").pop()?.mode === "auto_no_ui");
}

// --- scenario H: /specloop pick → gate → sendMessage(no turn) ---------------
{
	resetCaptures();
	const h = freshPi();
	specloopPi(h.pi as any);
	const ctx = makeCtx({ keys: [KEYS.space, KEYS.enter] }); // uncheck first of 2 recall hits
	await fire(h.handlers.session_start, "session_start", { reason: "startup" }, ctx);
	// seed firstPrompt via a first prompt (cancelled picker)
	const ctx2 = makeCtx({ keys: [KEYS.esc] });
	await fire(h.handlers.before_agent_start, "before_agent_start", { prompt: "the session first prompt", systemPrompt: "BASE" }, ctx2);
	await h.commands.specloop.handler("pick", ctx);
	ok("H: sendMessage once, triggerTurn:false", h.sent.length === 1 && h.sent[0].o?.triggerTurn === false);
	ok("H: picked content = unchecked-out hit (dedup lesson)",
		h.sent[0].m.content.includes("dedup") && !h.sent[0].m.content.includes("mock pi"));
	ok("H: customType specloop-recall", h.sent[0].m.customType === "specloop-recall");
	const ev = auditLines().filter((l) => l.event === "recall").pop();
	ok("H: audit phase=pick", ev?.phase === "pick");
	// /specloop pick with explicit query
	await h.commands.specloop.handler("pick explicit query words", ctx);
	ok("H: explicit query also works", h.sent.length === 2);
}

// --- scenario I: shutdown quit → recap spooled + unlinked by stub -----------
{
	resetCaptures();
	const h = freshPi();
	specloopPi(h.pi as any);
	const ctx = makeCtx({ keys: [KEYS.esc] });
	await fire(h.handlers.session_start, "session_start", { reason: "startup" }, ctx);
	await fire(h.handlers.before_agent_start, "before_agent_start", { prompt: "recap source prompt", systemPrompt: "BASE" }, ctx);
	await fire(h.handlers.session_shutdown, "session_shutdown", { reason: "quit" }, ctx);
	const ls = auditLines().filter((l) => l.event === "lifecycle");
	ok("I: recap_queued + recap_spawned audited",
		ls.some((l) => l.state === "recap_queued") && ls.some((l) => l.state === "recap_spawned"));
	await new Promise((r) => setTimeout(r, 500));
	const spoolDir = path.join(tmp, "spool");
	ok("I: spool dir empty (stub unlinked on completion)", !existsSync(spoolDir) || (await import("node:fs")).readdirSync(spoolDir).length === 0);
}

console.log(results.join("\n"));
console.log(`\n${results.filter((r) => r.startsWith("PASS")).length}/${results.length} passed  (tmp: ${tmp})`);
