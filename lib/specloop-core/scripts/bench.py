#!/usr/bin/env python3
"""Recall benchmark for specloop-core.

Indexes the memory split of a labeled corpus, runs the query split, and reports
Recall@k + MRR per embedder. This is how the embedding model is chosen
(references/testing.md §2, open-questions §2).

Usage:
  python3 bench.py
  python3 bench.py --corpus ../tests/corpus
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from engine import Embedder, HashEmbedder, Memory, PROVIDERS, make_embedder  # noqa: E402

KS = (1, 3, 5)


def load_corpus(corpus_dir: str):
    mem, qry = [], []
    for name, sink in (("memory.jsonl", mem), ("queries.jsonl", qry)):
        with open(os.path.join(corpus_dir, name)) as f:
            for line in f:
                line = line.strip()
                if line:
                    sink.append(json.loads(line))
    return mem, qry


def run(corpus_dir: str, embedders: list[Embedder]) -> None:
    mem, qry = load_corpus(corpus_dir)
    print(f"corpus: {len(mem)} memory nodes, {len(qry)} queries  ({corpus_dir})\n")
    header = f"{'embedder':<14} " + " ".join(f"R@{k:<4}" for k in KS) + " MRR"
    print(header)
    print("-" * len(header))
    n = len(qry) or 1
    for emb in embedders:
        m = Memory(":memory:", embedder=emb)
        for node in mem:
            m.index(node)
        hits = {k: 0 for k in KS}
        rr = 0.0
        for q in qry:
            ids = [r["id"] for r in m.recall(q["query"], k=max(KS), node_type=q.get("type"))]
            expected = set(q["expected_ids"])
            rank = next((i + 1 for i, x in enumerate(ids) if x in expected), None)
            if rank:
                rr += 1.0 / rank
            for k in KS:
                if any(x in expected for x in ids[:k]):
                    hits[k] += 1
        cells = " ".join(f"{hits[k]/n:<6.2f}" for k in KS)
        print(f"{emb.name:<14} {cells} {rr/n:.3f}")
        m.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus",
                    default=os.path.join(os.path.dirname(__file__), "..", "tests", "corpus"))
    args = ap.parse_args()
    embedders: list[Embedder] = [HashEmbedder()]
    for prov, cfg in PROVIDERS.items():
        if os.environ.get(cfg["key_env"]):
            try:
                embedders.append(make_embedder(prov))
            except Exception as e:  # pragma: no cover
                print(f"({prov} embedder skipped: {e})")
    if len(embedders) == 1:
        names = ", ".join(f"{c['key_env']}={c['name']}" for c in PROVIDERS.values())
        print(f"(no provider keys set — set one of: {names} to add remote embedders)")
    run(os.path.abspath(args.corpus), embedders)


if __name__ == "__main__":
    main()
