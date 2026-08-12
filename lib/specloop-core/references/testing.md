# Testing & benchmarking  *(specloop-core)*

> **The memory's value = retrieval quality.** If recall returns the wrong (or no) past recap, the memory is dead weight. So retrieval eval is THE test, not an afterthought. Everything below serves that.

## Build order
corpus → engine unit tests → recall bench (picks embedder) → wire extension → end-to-end. Don't wire the extension before the recall bench clears.

## 1. Labeled recall corpus — build FIRST (gating artifact)
~50–200 `(query → correct past recap)` pairs.
- **Seed from real past work** — actual session recaps. Synthetic data won't expose real recall failures because it won't match your real distribution.
- **Time-respect the split**: older recaps = memory; newer = queries. You can't recall the future, so don't split across time backwards.
- Use `mem export <dir> --scaffold-queries` to dump the live DB into corpus format, then **replace the scaffold (self-match) queries with realistic labels** — the scaffold only proves plumbing.
- Without this you can't measure recall quality OR pick the embedder.

## 2. Recall-quality bench — proves value + picks the embedder (open-Q §1)
Metrics (standard IR):
- **Recall@k** — did the correct recap appear in top-k? (k = 1, 3, 5)
- **MRR** — mean reciprocal rank (how high does it rank?).

**Embedder comparison (the bench auto-runs every provider whose key is set):**
- **mistral `mistral-embed`** (1024-dim) — documented, recommended.
- **zai `embedding-3`**, **openai `text-embedding-3-small`** — compare against mistral.
- `all-MiniLM-L6-v2` (ONNX, ~22 MB, 384-dim) — local, private baseline (off-Pi).

Confirm any provider with `scripts/smoke.py <provider>` + its key env. **Pick the smallest model whose Recall@5 is within ~2 pts of the best.**

## 3. Engine unit tests — cheap, deterministic
In-memory DB. Fast.
- `index` writes recap + embedding; `recall` returns correct top-k; `link` attaches `root_prompt_id`.
- **Dedup-on-write** (open-Q §4): a ≥0.98-similar recap merges, doesn't duplicate.
- **Scope** (open-Q §2): global vs `local` return different sets.

## 4. End-to-end: memory-ON vs memory-OFF — the only honest "does it help" test
- Seed N solved sessions; give the agent *similar but new* prompts; measure **solve-rate / iterations / tokens** with vs without the first-prompt recall.
- **Multiple samples per task.** The agent's *use* of recalled context is stochastic, and the net effect includes cases where memory **misleads** it. Catch those, not just the wins.

## 5. Pi resource bench — validates the backend choice
On the actual Pi hardware: recall latency **p50/p95** at 1k / 10k / 100k vectors; RAM footprint + DB-size growth. Confirms the backend holds; flags if/when to swap linear-scan for sqlite-vec.

## Practical notes
- **Version-control the corpus + bench script** so a regression surfaces the moment you change embedder / schema / recall ranking.
- Keep the corpus **append-only** with a schema-version tag so old results stay comparable.
- A recall-quality regression after a schema/embedder change is the single most useful signal you'll get.
