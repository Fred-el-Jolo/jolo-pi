/**
 * ExpandableText — a proper pi-tui component for text that would otherwise be
 * clipped to a single line with an ellipsis.
 *
 *   collapsed: one line per `collapsed` segment, truncated to the width with "…"
 *   expanded:  one word-wrapped block per `expanded` segment — the FULL text,
 *              ANSI styles preserved across wrapped lines (wrapTextWithAnsi)
 *
 * `collapsed` and `expanded` are independent segment lists on purpose: callers
 * often show a summary line when collapsed (e.g. only the THEN part) but the
 * full text when expanded. Both default to [] (renders nothing).
 *
 * Component contract (docs/tui.md): render(width) → string[] with EVERY line
 * ≤ width (the TUI hard-crashes otherwise), invalidate() on state that affects
 * rendering, optional handleInput. Results are cached per width like the other
 * components in this extension.
 *
 * Standalone usage works too (as the only custom component):
 *   new ExpandableText({ theme, collapsed: [{text, color}], expanded: [{text, color}] })
 * with "e" toggling via handleInput — or drive it programmatically with
 * toggle()/setExpanded() as the picker does (it owns the cursor, so "e" is
 * cursor-scoped there, not routed through this handleInput).
 */
import { truncateToWidth, visibleWidth, wrapTextWithAnsi } from "@earendil-works/pi-tui";

/** Structural slice of pi's Theme — the real Theme satisfies this. */
export type ThemeLike = {
	fg: (color: string, text: string) => string;
	bold: (text: string) => string;
};

/** One styled run of text: `color` is a theme token name (muted, dim, …). */
export type ExpandableSegment = { text: string; color: string };

export type ExpandableTextOptions = {
	theme: ThemeLike;
	collapsed?: ExpandableSegment[]; // rendered one-truncated-line-per-segment
	expanded?: ExpandableSegment[]; // rendered word-wrapped when open
	indent?: number; // spaces prefixed to every line (default 0)
	expandedByDefault?: boolean;
};

export class ExpandableText {
	private collapsedSegs: ExpandableSegment[];
	private expandedSegs: ExpandableSegment[];
	private theme: ThemeLike;
	private indent: number;
	private open: boolean;
	private cached: { width: number; lines: string[] } | null = null;

	constructor(opts: ExpandableTextOptions) {
		this.collapsedSegs = opts.collapsed ?? [];
		this.expandedSegs = opts.expanded ?? [];
		this.theme = opts.theme;
		this.indent = Math.max(0, opts.indent ?? 0);
		this.open = !!opts.expandedByDefault;
	}

	toggle(): boolean {
		this.open = !this.open;
		this.cached = null;
		return this.open;
	}

	setExpanded(v: boolean): void {
		if (v !== this.open) {
			this.open = v;
			this.cached = null;
		}
	}

	isExpanded(): boolean {
		return this.open;
	}

	/** "e" toggles (returns true = consumed); anything else is ignored. */
	handleInput(data: string): boolean {
		if (data === "e") {
			this.toggle();
			return true;
		}
		return false;
	}

	invalidate(): void {
		this.cached = null;
	}

	render(width: number): string[] {
		if (this.cached && this.cached.width === width) return this.cached.lines;
		const avail = Math.max(1, width - this.indent); // wrapTextWithAnsi needs ≥ 1
		const pad = " ".repeat(this.indent);
		const segs = this.open ? this.expandedSegs : this.collapsedSegs;
		const lines: string[] = [];
		for (const seg of segs) {
			if (!seg.text) continue;
			const styled = this.theme.fg(seg.color, seg.text);
			if (this.open) {
				for (const l of wrapTextWithAnsi(styled, avail)) lines.push(pad + l);
			} else {
				lines.push(pad + truncateToWidth(styled, avail, "…"));
			}
		}
		// width contract is non-negotiable: clamp whatever happened above
		const clamped = lines.map((l) => (visibleWidth(l) > width ? truncateToWidth(l, width) : l));
		this.cached = { width, lines: clamped };
		return clamped;
	}
}
