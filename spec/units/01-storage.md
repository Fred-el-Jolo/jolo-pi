# Unit: Store  *(persistence + cosine search + dedup/merge dispatch)*

> File: `lib/specloop-core/scripts/engine.py` — class `Memory`.

## What it does

A flat sqlite store of nodes plus a linear-scan cosine index. It persists nodes,
answers top-k similarity queries (`recall`), and routes `index()` to the right
per-type **dedup/merge policy**. It knows nothing about lessons, recaps, prompts,
or models — only nodes, vectors, and types. That blindness is the boundary.

## How to use it (interface)

```python
class Memory:
    def index(self, node: dict) -> str            # insert, or merge onto an existing id
    def recall(self, query: str, k=5, scope="global", type=None) -> list[hit]
    def history(self, root_id: str) -> list[node]  # a node + everything linked to it
    def count(self, type=None) -> int
```

- `index(node)` returns the id used — **may be an existing id if the dedup/merge
  policy merged**. Callers must not assume a new node was created.
- `recall` redacts the query, embeds it, ranks by `cosine(q, node.embedding)`,
  returns hits with `_score`. `type` filters (e.g. `type="lesson"`).
- Construction takes an **Embedder** (dependency injection): `Memory(path,
  embedder, current_project)`. `HashEmbedder` (lexical, zero-dep) ships for
  tests/offline; `make_embedder("mistral")` for production.

## What it depends on

- An **Embedder** (`embed(text)→list[float]`): `engine.HashEmbedder` or any
  `EmbedderAPI` (`mistral`/`zai`/`openai`). Swappable; switching after data
  exists raises on dim-mismatch (see `_cosine` guard) rather than corrupting rank.
- A **DedupMerger** registry (see [03-dedup-merge](03-dedup-merge.md)): `index()`
  looks up the policy for `node["type"]`; if none, it inserts unconditionally.

## Node schema

```
nodes(
  id, type, root_prompt_id, project, created,
  body,            -- the PAYLOAD (what gets injected on recall)
  meta (json),     -- type-specific structured fields
  embedding,       -- the MATCH KEY (vector used for cosine + dedup)
  embedding_prompt -- LEGACY (recap type only); unused by lessons
)
```

Two shapes coexist; only `lesson` is actively written.

### `lesson`  *(the M2 node — new)*
```
body      = "WHEN {when} THEN {then}"            # rendered full rule (payload)
embedding = embed(redact(when))                  # WHEN clause only (match key + dedup key)
meta = {
  when, then,                                    # the split parts (for re-render / re-embed)
  status:    confirmed | tentative | contested,  # see 04-status.md
  session:   <pi session id>,
  confirmed_by: [<session id>, ...],             # reinforcement count
  merge_count:  int,
  provenance: [{then, status, session, date}, ...]   # only if ever LLM-merged
}
```
**Why `embedding` holds the WHEN vector, not the body:** key/payload separation
(see [README §Design principles](../README.md#design-principles-apply-to-every-unit)).
The WHEN is both the recall key and the dedup key — one vector, two uses, so no
separate prompt-vector column is needed for this type.

### `recap`  *(legacy — write-frozen)*
Unchanged from M0 (`references/memory-model.md`): prose body, `embedding =
embed(body)`, dedup on `initial_prompt`. **No new recap nodes are written.**
Existing ones remain readable; see [07-migration](07-migration.md).

## Behaviours carried over unchanged from M0

- **Redaction at the write boundary** — `body` and redact-listed meta fields are
  scrubbed (`redact.py`) before embed/persist; the recall query is redacted to
  compare in the same scrubbed space. Gated by `SPECLOOP_REDACT` (default ON).
- **Cosine dim-mismatch guard** — `_cosine` raises `ValueError` on
  `len(a) != len(b)` (the switching-provider failure mode).
- **Scope** — global by default; `scope="local"` restricts to `current_project`.

## Testability

In-memory DB (`Memory(":memory:", HashEmbedder())`) — no files, no network.
`index`/`recall`/`history`/`count` are pure given a fixed embedder. Dedup/merge
is exercised by injecting a stub `DedupMerger` (see [03](03-dedup-merge.md) tests).
