# Recall corpus  *(the gating test artifact)*

Labeled `(query → correct past recap)` pairs used to measure recall quality and
pick the embedding model (see [../../references/testing.md](../../references/testing.md)).

## Files
- `memory.jsonl` — the **memory** split: one recap per line, what gets indexed.
- `queries.jsonl` — the **query** split: one query per line, what recall is tested against.

## memory.jsonl — recap fields
```json
{"id":"recap-db-01","type":"recap","project":"proj-alpha","body":"Fixed postgres connection pool exhaustion under load by raising the pool size.","meta":{"status":"done","initial_prompt":"db connection timeouts under load"}}
```
- `id` — stable id; queries reference it.
- `type` — `recap` (the only node type; see [../../references/memory-model.md](../../references/memory-model.md)).
- `project` — scope key (`scope='local'` filters on it).
- `body` — the recap summary text that gets embedded.
- `meta` — `status` (`done` | `partial` | `failed`), `initial_prompt`, and `session` (when set).

## queries.jsonl — query fields
```json
{"query":"db connection timeout under load","expected_ids":["recap-db-01"],"type":"recap"}
```
- `query` — text to embed & search with.
- `expected_ids` — the recap id(s) that **should** be retrieved (the label).
- `type` — optional; restricts recall to that node type.

## ⚠️ This seed is SYNTHETIC
`memory.jsonl` / `queries.jsonl` here are placeholder data with deliberate lexical
overlap so the bench runs out-of-the-box with the zero-dep `HashEmbedder`. **Replace
with your real past session recaps** — synthetic data will not reflect your real
recall quality (testing.md §1: seed from real work; time-respect the split). The seed
exists only to prove the harness runs and to exercise the engine. Use
`mem export <dir> --scaffold-queries` to dump your live DB into this format, then
replace the scaffold queries with realistic labels.
