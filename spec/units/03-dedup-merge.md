# Unit: Dedup + Merge policies  *(same-trigger? → confirm or reconcile)*

> Files: `engine.py` (policy dispatch) + `semantic.py` (`merge_thens`).

## What it does

When a new lesson is indexed and its **WHEN vector** is near-identical to an
existing lesson's, this unit decides (a) whether they are truly the *same
trigger situation*, and if so (b) how to reconcile their THENs into one node —
**losslessly** (no learnings dropped without a stated reason). It never runs for
non-lesson types.

It is two cooperating policies plus one LLM call:

| Stage | Decides | Cost |
|---|---|---|
| **Dedup (candidate)** | is there a WHEN-vector match ≥ threshold? | 1 embed (the new WHEN) + linear scan |
| **Merge — fast path** | are the THENs already near-identical? | 0 LLM (THEN-vector cosine) |
| **Merge — arbiter + reconcile** | same trigger? if yes, merge THENs | 1 LLM call (`merge_thens`) |

## How to use it (interface)

```python
# semantic.py
def merge_thens(chatter, when, a: ThenInput, b: ThenInput) -> dict:
    """a, b carry {then, status, confirmed_by, date}. Returns:
       {same_trigger: bool, then: str, status: str, dropped: [{item, reason}]}.
       If same_trigger is False, the other fields are ignored by the caller."""

# engine.py — the Store calls the policy registered for type 'lesson':
policy.find_candidate(store, when_vec, project) -> Optional[str]   # existing node id
policy.merge(store, existing_id, new_node) -> MergeOutcome         # FAST_PATH | MERGED | NOT_A_DUP
```

`MergeOutcome.NOT_A_DUP` tells the Store to **insert the new lesson as its own
node** (the vector match was a false positive — different triggers).

## Algorithm (the full flow, per new lesson)

```
1. DEDUP      candidate = best existing lesson with cosine(when_vec, cand.when_vec) ≥ LESSON_DEDUP_THRESHOLD (0.92)
              (same project scope)
              if none → INSERT new lesson. done.

2. FAST PATH  if cosine(embed(then_new), embed(cand.then)) ≥ THEN_IDENTICAL_THRESHOLD (0.95):   # re-learned
                 bump cand.confirmed_by += [new.session]; cand.merge_count += 1
                 trend cand.status: tentative→confirmed once |confirmed_by| ≥ CONFIRM_TO_CONFIRMED (2)
                 body + embedding UNCHANGED (THEN ≈ identical ⇒ body ≈ unchanged; WHEN unchanged ⇒ embedding unchanged). audit MERGE(fast). done.

3. ARBITER    res = merge_thens(chatter, when, cand.then-input, new.then-input)
              if res.same_trigger == False → NOT_A_DUP → INSERT new lesson. done.

4. RECONCILE  (same trigger, THENs differ) → UPDATE the existing node IN PLACE:
                 body      = "WHEN {when} THEN {res.then}"     # WHEN unchanged (stable id, v1)
                 embedding = UNCHANGED                        # = embed(when); see note
                 meta.then = res.then
                 meta.status        = res.status              # per authority rules below
                 meta.confirmed_by  = union(cand, new)        # accumulate reinforcement
                 meta.merge_count  += 1
                 meta.provenance    = cand.provenance + [{then:new.then, status, session, date}]
                 audit MERGE(llm) with res.dropped.
```

**WHY the existing node survives (stable id):** ids are referenced by the audit
log and by `meta.provenance`. Updating in place keeps them stable while content
evolve. The WHEN/embedding are deliberately **not** refined in v1
(refining the key churns the match vector); revisit if keys drift. See
[07-migration §Constants](07-migration.md#constants--tunables).

## The `merge_thens` prompt contract

> You reconcile two lessons that may describe the SAME trigger situation. Inputs:
> the shared WHEN, and two THEN takeaways — each with an authority (`status`) and
> an age. Return STRICT JSON:
> `{"same_trigger": bool, "then": str, "status": str, "dropped": [{"item": str, "reason": str}]}`.
>
> - **`same_trigger`** = `false` if the two THENs are actually about *different*
>   situations — then this is not a merge; the caller keeps them separate and the
>   other fields are ignored.
> - If same trigger, produce ONE merged `then` that:
>   1. **unions** all distinct actionable items from both sides (lossless),
>   2. **removes near-duplicates**,
>   3. **resolves contradictions by authority** — never keep both sides of a
>      contradiction silently (see authority ordering below),
>   4. **orders by required dependency first, then efficiency** — most likely to
>      apply/fix first; treat ordered *steps* (causal) differently from unordered
>      *conditions* (a set),
>   5. **caps at 6 items**, dropping only duplicates or the lowest-value item —
>      each drop recorded in `dropped` with a reason; never drop a unique item
>      silently.
> - **`status`**: `confirmed` if all sources confirmed; `tentative` if mixed but
>   uncontradicted; `contested` if a contradiction could not be resolved.

## Conflict-resolution authority  *(ordering, on a contradiction)*

Two THENs often disagree (e.g. A: "use rpi-clone"; B: "rpi-clone broke, use
piclone"). Unioning blindly yields a self-contradictory rule. Resolve by this
precedence (formalised as expert-system conflict resolution):

1. **Status rank** — `confirmed (3) > tentative (2) > contested (1)`.
2. **Confirm-count** — more distinct sessions ≥ fewer.
3. **Recency** — newer ≥ older (knowledge evolves; an old rule may be stale).

The merged `status` follows the table in [04-status](04-status.md#merged-status-rules).

## Explicitly NOT done: specificity nesting

A more-specific WHEN ("deploy Jekyll *to a subpath*") is a **different trigger**,
not a nested exception inside a general rule's THEN. Under WHEN-only embedding,
nesting would bury the specific lesson in a payload retrievable only via a
coarser vector — strictly worse than giving it its own WHEN. So: **different
WHEN ⇒ different node.** The arbiter's `same_trigger=false` is exactly this case,
and the merge never nests. (See design-review retraction; do not re-introduce.)

## What it depends on

- A **Chatter** (only on the LLM path; the fast path is vector-only).
- An **Embedder** for the fast-path THEN-similarity check (computed on demand,
  not persisted). Embedding the WHEN at index time is the **Store's** job
  ([01](01-storage.md)).
- The **Store** (to read the candidate, write the update).

## Testability

Inject a fake Chatter whose `merge_thens.complete()` returns canned JSON. Assert,
per branch: candidate-found/none, fast-path bumps `confirmed_by` and trends
status, `same_trigger=false` ⇒ new node inserted (count rises), LLM path ⇒
existing node updated in place (id stable, body changed, provenance appended,
`dropped` honoured), authority picks the higher-status side on contradiction,
length cap drops lowest-value-with-reason. No network; `HashEmbedder` suffices.
