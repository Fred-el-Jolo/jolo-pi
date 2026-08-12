#!/usr/bin/env python3
"""One-call smoke test for any registered embedding provider. Confirms the
endpoint, model, response shape, and dimension using YOUR key.

    export MISTRAL_API_KEY=...        # or ZAI_API_KEY / OPENAI_API_KEY
    python3 smoke.py mistral          # or zai / openai   (default: mistral)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from engine import PROVIDERS, make_embedder  # noqa: E402

prov = sys.argv[1] if len(sys.argv) > 1 else "mistral"
if prov not in PROVIDERS:
    print(f"unknown provider '{prov}'. known: {', '.join(PROVIDERS)}")
    sys.exit(2)
try:
    emb = make_embedder(prov)
except RuntimeError as e:
    print(e)
    sys.exit(1)

vec = emb.embed("postgres connection pool timeout under load")
print(f"provider: {emb.name}")
print(f"url:      {emb.url}")
print(f"model:    {emb.model}")
print(f"dim:      {len(vec)}")
print(f"first5:   {[round(x, 4) for x in vec[:5]]}")
print(f"OK — {prov} embeddings work. Run the bake-off:  python3 bench.py")
