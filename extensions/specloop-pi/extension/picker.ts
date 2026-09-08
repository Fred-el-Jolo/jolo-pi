/**
 * specloop-pi picker — the validation gate for memory injection ("no magic").
 *
 * Before anything enters LLM context, the candidate recalls are shown to the
 * user as a checkbox list rendered in the terminal ONLY (nothing here is sent
 * to the model — injection happens solely via the caller's return value,
 * built from the checked subset). Esc → cancel (insert nothing). An optional
 * deadline auto-cancels for unattended runs.
 *
 * Three layers:
 *   RecallPickerComponent  raw TUI component (render/handleInput/invalidate)
 *   confirmGate()          mode-aware gate: tui picker → rpc confirm → auto
 *
 * The gate NEVER throws: on any picker/UI error it fails open (auto-include,
 * audited by the caller via `mode: "picker_error"`), because memory must not
 * break the run. Modes without a UI (print/-p, --mode json) auto-include.
 */
import { Key, matchesKey, truncateToWidth } from "@earendil-works/pi-tui";
import { clip, type RecallHit } from "./mem.ts";

/** Structural slice of pi's Theme — the real Theme satisfies this. */
export type ThemeLike = {
	fg: (color: string, text: string) => string;
	bold: (text: string) => string;
};

export type PickOutcome = { kind: "confirm"; chosen: RecallHit[] } | { kind: "cancel" };

/** Split a lesson body ("WHEN x THEN y") into two display lines. */
export function splitLesson(body: string): { when: string; then: string } {
	const i = (body || "").search(/\bTHEN\b/i);
	if (i < 0) return { when: clip(body, 90), then: "" };
	return { when: clip(body.slice(0, i).trim(), 90), then: clip(body.slice(i).trim(), 110) };
}

export class RecallPickerComponent {
	private items: RecallHit[];
	private theme: ThemeLike;
	private onDone: (outcome: PickOutcome) => void;
	private onDirty: () => void;
	private checked: boolean[];
	private cursor = 0;
	private cached: { width: number; lines: string[] } | null = null;
	private finished = false;
	private deadline: number | null;
	private ticker: ReturnType<typeof setInterval> | null = null;

	constructor(
		items: RecallHit[],
		theme: ThemeLike,
		onDone: (outcome: PickOutcome) => void,
		onDirty: () => void,
		timeoutMs = 0, // 0 = wait for the user indefinitely (Esc always works)
	) {
		this.items = items;
		this.theme = theme;
		this.onDone = onDone;
		this.onDirty = onDirty;
		this.checked = items.map(() => true); // default: everything pre-checked
		this.deadline = timeoutMs > 0 ? Date.now() + timeoutMs : null;
		if (this.deadline !== null) {
			this.ticker = setInterval(() => {
				if (this.deadline !== null && Date.now() >= this.deadline) {
					this.finish({ kind: "cancel" });
				} else {
					this.cached = null; // refresh the countdown display
					this.onDirty();
				}
			}, 1000);
		}
	}

	private finish(outcome: PickOutcome): void {
		if (this.finished) return;
		this.finished = true;
		if (this.ticker) clearInterval(this.ticker);
		this.onDone(outcome);
	}

	private move(d: number): void {
		const next = Math.min(this.items.length - 1, Math.max(0, this.cursor + d));
		if (next !== this.cursor) {
			this.cursor = next;
			this.cached = null;
		}
	}

	private toggle(i = this.cursor): void {
		this.checked[i] = !this.checked[i];
		this.cached = null;
	}

	private toggleAll(): void {
		const all = this.checked.every(Boolean);
		this.checked = this.checked.map(() => !all);
		this.cached = null;
	}

	handleInput(data: string): void {
		if (this.finished) return;
		if (matchesKey(data, Key.up) || data === "k") this.move(-1);
		else if (matchesKey(data, Key.down) || data === "j") this.move(1);
		else if (matchesKey(data, Key.space)) this.toggle();
		else if (data === "a") this.toggleAll();
		else if (matchesKey(data, Key.enter)) {
			this.finish({ kind: "confirm", chosen: this.items.filter((_, i) => this.checked[i]) });
		} else if (matchesKey(data, Key.escape)) {
			this.finish({ kind: "cancel" });
		}
	}

	render(width: number): string[] {
		if (this.cached && this.cached.width === width) return this.cached.lines;
		const t = this.theme;
		const n = this.items.length;
		const lines: string[] = [];
		lines.push(
			t.fg("accent", t.bold(`specloop — ${n} related memor${n === 1 ? "y" : "ies"} found`)),
		);
		lines.push(t.fg("dim", "check the memories to insert into this session's context"));
		lines.push("");
		this.items.forEach((hit, i) => {
			const cursor = i === this.cursor ? "❯ " : "  ";
			const box = this.checked[i] ? t.fg("success", "[x]") : t.fg("dim", "[ ]");
			const score = t.fg("dim", (hit._score ?? 0).toFixed(2));
			const { when, then } = splitLesson(hit.body || "");
			const head = t.fg(i === this.cursor ? "accent" : "text", when);
			lines.push(truncateToWidth(`${cursor}${box} ${score} ${head}`, width));
			if (then) lines.push(truncateToWidth(`     ${t.fg("muted", then)}`, width));
		});
		lines.push("");
		let help = "↑↓ move · space toggle · a all/none · enter insert checked · esc insert none";
		if (this.deadline !== null) {
			help += ` · auto-skip in ${Math.max(0, Math.ceil((this.deadline - Date.now()) / 1000))}s`;
		}
		lines.push(t.fg("dim", help));
		this.cached = { width, lines };
		return lines;
	}

	invalidate(): void {
		this.cached = null;
	}
}

// ---- mode-aware gate -------------------------------------------------------

export type GateCtx = { mode?: string; hasUI?: boolean; ui?: any };
export type GateResult = {
	chosen: RecallHit[]; // subset of `hits` the user accepted ([] = none)
	mode: string; // "picker" | "rpc_confirm" | "auto_no_ui" | "picker_error"
	cancelled: boolean; // true = user explicitly declined everything
};

/**
 * Show `hits` to the user and return the accepted subset.
 *  - TUI:  interactive checkbox picker (ctx.ui.custom — terminal pixels only)
 *  - RPC:  single confirm dialog (custom() is unavailable there)
 *  - no UI (print/-p, --mode json): auto-include (previous behavior)
 * Never throws — fail-open on picker errors.
 */
export async function confirmGate(
	ctx: GateCtx,
	hits: RecallHit[],
	pickTimeoutMs = 0,
): Promise<GateResult> {
	const custom = ctx.ui?.custom as
		| ((factory: any, options?: any) => Promise<PickOutcome | null>)
		| undefined;
	if (ctx.mode === "tui" && typeof custom === "function") {
		try {
			const outcome = await custom(
				(tui: any, theme: ThemeLike, _kb: any, done: (o: PickOutcome | null) => void) => {
					const c = new RecallPickerComponent(
						hits,
						theme,
						(o) => done(o),
						() => tui.requestRender(),
						pickTimeoutMs,
					);
					return {
						render: (w: number) => c.render(w),
						invalidate: () => c.invalidate(),
						handleInput: (data: string) => {
							c.handleInput(data);
							tui.requestRender();
						},
					};
				},
			);
			if (outcome) {
				return {
					chosen: outcome.kind === "confirm" ? outcome.chosen : [],
					mode: "picker",
					cancelled: outcome.kind === "cancel",
				};
			}
			return { chosen: [], mode: "picker", cancelled: true }; // defensive: unresolved custom()
		} catch {
			return { chosen: hits, mode: "picker_error", cancelled: false }; // fail open
		}
	}
	if (ctx.hasUI && typeof ctx.ui?.confirm === "function") {
		try {
			const preview = hits
				.map((h) => {
					const { when } = splitLesson(h.body || "");
					return `(${(h._score ?? 0).toFixed(2)}) ${when}`;
				})
				.join("\n");
			const ok = await ctx.ui.confirm(
				`specloop: insert ${hits.length} recalled memor${hits.length === 1 ? "y" : "ies"}?`,
				preview,
			);
			return { chosen: ok ? hits : [], mode: "rpc_confirm", cancelled: !ok };
		} catch {
			return { chosen: hits, mode: "picker_error", cancelled: false }; // fail open
		}
	}
	return { chosen: hits, mode: "auto_no_ui", cancelled: false };
}
