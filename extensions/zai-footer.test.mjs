/**
 * zai-footer.test.mjs — red/green probe for the NaN-on-absent-fields bug.
 *
 * Run: node extensions/zai-footer.test.mjs   (Node ≥23 strips types natively)
 * Import target: the REAL buildStatus from zai-footer.ts (theme.fg passthrough
 * so assertions see plain text).
 */
import assert from "node:assert/strict";
import { buildStatus } from "./zai-footer.ts";

const T = 1_780_000_000_000; // fixed "now" — deterministic countdowns
const theme = { fg: (_token, text) => text };

const mk = (five, wk) => ({
	level: "L1",
	limits: [
		{
			type: "CREDIT_LIMIT", unit: 3, number: 5,
			usage: 100, currentValue: 42, remaining: 58,
			percentage: 42, nextResetTime: T + 3600_000, ...five,
		},
		{
			type: "CREDIT_LIMIT", unit: 6, number: 1,
			usage: 10000, currentValue: 230, remaining: 9770,
			percentage: 2.3, nextResetTime: T + 5 * 86400_000, ...wk,
		},
	],
});

// ISC-1: absent numeric fields (no usage window started) never render NaN/dirty
{
	const out = buildStatus(theme, mk({ nextResetTime: undefined }, { nextResetTime: null, percentage: null }), T);
	assert.ok(!/NaN/.test(out), `NaN leaked: ${out}`);
	assert.ok(!/null|undefined/.test(out), `dirty render: ${out}`);
}

// ISC-2 (Anti): absent reset time never hides a renderable percentage
{
	const out = buildStatus(theme, mk({ nextResetTime: undefined }, {}), T);
	assert.ok(out.includes("⚡5h 42%"), `5h pct hidden: ${out}`);
	assert.ok(!/⚡5h 42% · ↻/.test(out), `5h countdown should be absent: ${out}`);
	assert.ok(out.includes("wk 2.3%"), `weekly pct hidden: ${out}`);
}

// ISC-3 (regression): valid quota renders pct + countdown for both windows
{
	const out = buildStatus(theme, mk({}, {}), T);
	assert.ok(/⚡5h 42% · ↻1h00m/.test(out), `5h segment: ${out}`);
	assert.ok(/wk 2\.3% · ↻5d00h/.test(out), `weekly segment: ${out}`);
	assert.ok(/[●○]/.test(out), `peak dot missing: ${out}`);
}

// ISC-5 support: % is relayed byte-for-byte, never recomputed locally
{
	const out = buildStatus(theme, mk({ percentage: 37.7 }, { percentage: 84.2 }), T);
	assert.ok(out.includes("⚡5h 37.7%") && out.includes("wk 84.2%"), `not pass-through: ${out}`);
}

console.log("zai-footer.test: all assertions passed");
