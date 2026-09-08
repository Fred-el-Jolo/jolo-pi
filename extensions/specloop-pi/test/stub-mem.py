#!/usr/bin/env python3
"""Stub mem.py for the extension mock test. Logs every invocation to <tmp>/calls.log."""
import json, os, sys

args = sys.argv[1:]
cmd = args[0] if args else ""

with open(os.environ["STUB_CALLS"], "a") as f:
    f.write(cmd + "\n")

def out(x):
    print(json.dumps(x))

RECALLS = [
    {"id": "n1", "type": "lesson", "body": "WHEN pi extension tests hang THEN drive logic through a mock pi", "meta": {}, "_score": 0.90},
    {"id": "n2", "type": "lesson", "body": "WHEN dedup threshold too high THEN measure on the live store", "meta": {}, "_score": 0.72},
    {"id": "n3", "type": "lesson", "body": "WHEN z.ai quota footer dims THEN bump dimGray in the theme", "meta": {}, "_score": 0.55},
]

if cmd == "stats":
    out({"nodes": {"lesson": 3}})
elif cmd == "start":
    out({"recalls": RECALLS})
elif cmd == "recall":
    out(RECALLS[:2])
elif cmd == "recap":
    sys.stdin.read()
    if "--spool-file" in args:
        sf = args[args.index("--spool-file") + 1]
        if os.path.exists(sf):
            os.unlink(sf)
    sys.exit(0)
else:
    sys.exit(2)
