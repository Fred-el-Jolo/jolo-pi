/**
 * z.ai quota footer segment  (tier B — LIVE account quota)
 * ========================================================
 * Augments pi's DEFAULT footer (via ctx.ui.setStatus) with real z.ai quota
 * pulled from the account API, so the built-in footer info stays intact.
 *
 *   ⚡5h 95% · ↻1h27m │ wk 23% · ↻2d04h · ●
 *
 * Source: GET https://api.z.ai/api/monitor/usage/quota/limit  (Bearer <zai key>)
 *   → { data: { level, limits: [ {usage:cap, currentValue:used, remaining,
 *       percentage:%used, nextResetTime:epochMs}, … (5h, weekly) ] } }
 *
 * Why this replaced the session-credit estimate (tier A): the API gives the
 * actual account-wide remaining/used/reset, which is what "how much do I have
 * left?" really wants. Per-turn credit math (multipliers/off-peak) is gone.
 *
 * Refresh: on session_start + turn_end, plus a background poll (POLL_MS) so the
 * countdown/reset stays correct while idle. Fetches are async + never block
 * render (we setStatus the cached result). The interval is unref'd and dedup'd
 * across /reload via globalThis.
 *
 * TEST:   pi -e extensions/zai-footer.ts     APPLY: symlink to ~/.pi/agent/extensions/
 * Decision knobs at the top (POLL_MS, near-limit thresholds).
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

// ── config / decisions ───────────────────────────────────────────────────
const ENDPOINT = "https://api.z.ai/api/monitor/usage/quota/limit";
const STATUS_KEY = "zai";
/** Background refresh interval. Lower = fresher + more API calls. */
const POLL_MS = 60_000;
/** Fetch timeout. */
const FETCH_TIMEOUT_MS = 8_000;
/** Delay after a turn before fetching, so z.ai's counter catches up. */
const TURN_END_DELAY_MS = 1_500;
/** Color the 5h number warning/error at these %used thresholds. */
const WARN_AT_PCT = 90;
const ERROR_AT_PCT = 100;

// ── types ─────────────────────────────────────────────────────────────────
interface Limit {
	type: string;
	unit: number;
	number: number;
	usage: number; // cap
	currentValue: number; // used
	remaining: number;
	percentage: number; // % used
	nextResetTime: number; // epoch ms
}
interface QuotaData {
	limits: Limit[];
	level: string;
}
interface QuotaResp {
	code: number;
	success: boolean;
	msg?: string;
	data?: QuotaData;
}

// ── helpers ───────────────────────────────────────────────────────────────

/** True when Singapore time (UTC+8) is outside Mon–Fri 14:00–18:00. */
function isOffPeakSGT(now = new Date()): boolean {
	const sgt = new Date(now.getTime() + (now.getTimezoneOffset() + 8 * 60) * 60_000);
	const day = sgt.getUTCDay(); // 0=Sun … 6=Sat
	const hour = sgt.getUTCHours();
	return !((day >= 1 && day <= 5) && (hour >= 14 && hour < 18));
}

/** "1h05m" / "5m" / "12s" countdown to a future epoch ms (minutes zero-padded). */
function fmtDur(target: number, now = Date.now()): string {
	let s = Math.max(0, Math.round((target - now) / 1000));
	const h = Math.floor(s / 3600);
	s %= 3600;
	const m = Math.floor(s / 60);
	s %= 60;
	if (h > 0) return `${h}h${String(m).padStart(2, "0")}m`;
	if (m > 0) return `${m}m`;
	return `${s}s`;
}

/** "2d04h" / "5h09m" / "3m" countdown to a future epoch ms (hours zero-padded). */
function fmtDurWk(target: number, now = Date.now()): string {
	let s = Math.max(0, Math.round((target - now) / 1000));
	const d = Math.floor(s / 86400);
	s %= 86400;
	const h = Math.floor(s / 3600);
	s %= 3600;
	const m = Math.floor(s / 60);
	if (d > 0) return `${d}d${String(h).padStart(2, "0")}h`;
	if (h > 0) return `${h}h${String(m).padStart(2, "0")}m`;
	return `${m}m`;
}

let cachedKey: string | null | undefined;
function readKey(): string | null {
	if (cachedKey !== undefined) return cachedKey;
	try {
		const dir = process.env.PI_CODING_AGENT_DIR || path.join(os.homedir(), ".pi/agent");
		const auth = JSON.parse(fs.readFileSync(path.join(dir, "auth.json"), "utf8"));
		cachedKey = auth?.zai?.key ?? null;
	} catch {
		cachedKey = null;
	}
	return cachedKey;
}

async function fetchQuota(key: string): Promise<QuotaData | null> {
	const ctrl = new AbortController();
	const t = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS);
	try {
		const r = await fetch(ENDPOINT, {
			headers: { Authorization: `Bearer ${key}`, Accept: "application/json" },
			signal: ctrl.signal,
		});
		if (!r.ok) return null;
		const j = (await r.json()) as QuotaResp;
		return j.success && j.data ? j.data : null;
	} finally {
		clearTimeout(t);
	}
}

/**
 * Build the footer segment. Limits are sorted by nextResetTime: nearest reset
 * = the 5h window, farthest = weekly (robust regardless of unit/number codes).
 */
/** Width-1 (non-emoji) symbols for the peak / off-peak window. */
const PEAK_ON = "●"; // filled = peak (on)
const PEAK_OFF = "○"; // hollow = off-peak (off)

function buildStatus(
	theme: { fg: (token: string, text: string) => string },
	data: QuotaData,
	now = Date.now(),
): string {
	const limits = [...data.limits].sort((a, b) => a.nextResetTime - b.nextResetTime);
	const fiveH = limits[0];
	const weekly = limits[1];
	const peakNow = !isOffPeakSGT();
	const parts: string[] = [];

	if (fiveH) {
		const color =
			fiveH.percentage >= ERROR_AT_PCT
				? "error"
				: fiveH.percentage >= WARN_AT_PCT
					? "warning"
					: "accent";
		parts.push(theme.fg(color, `⚡5h ${fiveH.percentage}%`));
		parts.push(theme.fg("dim", ` · ↻${fmtDur(fiveH.nextResetTime, now)}`));
	}
	if (weekly) {
		parts.push(
			theme.fg("dim", ` │ wk ${weekly.percentage}% · ↻${fmtDurWk(weekly.nextResetTime, now)}`),
		);
	}
	parts.push(theme.fg("dim", " │ "));
	parts.push(theme.fg(peakNow ? "warning" : "success", peakNow ? PEAK_ON : PEAK_OFF));
	return parts.join("");
}

// ── pi wiring ─────────────────────────────────────────────────────────────

const g = globalThis as { __zaiTimer?: ReturnType<typeof setInterval> };
if (g.__zaiTimer) clearInterval(g.__zaiTimer); // dedupe across /reload

let lastCtx: any = null;
let lastData: QuotaData | null = null;
let visible = true;
let inFlight = false;

function paint(ctx: any) {
	if (!visible) {
		ctx.ui.setStatus(STATUS_KEY, undefined);
		return;
	}
	if (lastData) ctx.ui.setStatus(STATUS_KEY, buildStatus(ctx.ui.theme, lastData));
}

async function refresh(ctx: any) {
	lastCtx = ctx;
	if (inFlight) return;
	const key = readKey();
	if (!key) return;
	inFlight = true;
	try {
		const data = await fetchQuota(key);
		if (data) {
			lastData = data;
			paint(ctx);
		}
	} catch (e) {
		console.warn("[zai-footer] quota fetch failed:", (e as Error).message);
	} finally {
		inFlight = false;
	}
}

function ensurePolling() {
	if (g.__zaiTimer) return;
	g.__zaiTimer = setInterval(() => {
		if (lastCtx) void refresh(lastCtx);
	}, POLL_MS);
	g.__zaiTimer.unref?.(); // don't keep the process alive
}

export default function (pi: ExtensionAPI) {
	pi.on("session_start", async (_e, ctx) => {
		ensurePolling();
		await refresh(ctx);
	});
	pi.on("turn_end", async (_e, ctx) => {
		ensurePolling();
		// small delay so z.ai's counter reflects the turn that just ended
		setTimeout(() => void refresh(ctx), TURN_END_DELAY_MS);
	});
	pi.registerCommand("zai", {
		description: "Toggle the z.ai quota footer segment",
		handler: async (_args, ctx) => {
			visible = !visible;
			if (visible) await refresh(ctx);
			else paint(ctx);
			ctx.ui.notify(visible ? "z.ai footer on" : "z.ai footer off", "info");
		},
	});
}
