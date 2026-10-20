"""tests/compute_reward.py: every scoring decision, then reward.txt, reward.json and details.json on every path."""
import json
from pathlib import Path

OUT = Path("/logs/verifier")


def emit(reward, valid, reason, subscores):
    reward = round(min(1.0, max(0.0, reward)), 6)
    flat = {"reward": reward, "score": reward, "valid": int(valid)}
    flat.update({k: round(float(v), 6) for k, v in subscores.items()})   # flat, numbers only
    (OUT / "reward.json").write_text(json.dumps(flat))
    (OUT / "reward.txt").write_text(f"{reward}\n")
    (OUT / "details.json").write_text(json.dumps({
        "subscores": [{"name": k, "score": v} for k, v in subscores.items()],
        "additional_data": {"reason": reason},
    }))
    raise SystemExit(0 if reward > 0 else 1)


try:
    ev = json.loads((OUT / "evidence.json").read_text())
except Exception as e:
    emit(0.0, 0, f"no evidence: {type(e).__name__}", {})

if not ev.get("runtime_ok", False):                       # the harness failed, not the agent
    emit(0.0, 0, "runtime unavailable: " + str(ev.get("runtime_error", "")), {})
if ev.get("cheat_detected") or not ev.get("build_ok"):    # hard gates first
    emit(0.0, 1, ev.get("gate_reason") or "build failed", {"correctness": 0.0})

# Implementation shape: weighted fraction of the fixed hidden set, normalized to what the reference passes.
buckets = ev.get("buckets") or {}
wsum = sum(b["weight"] for b in buckets.values())
if wsum <= 0 or not ev.get("cases_total"):
    emit(0.0, 0, "evidence has no cases (verifier fault)", {})
score = sum(b["weight"] * b["passed"] / b["total"] for b in buckets.values() if b["total"]) / wsum
subs = {f"bucket_{k}": b["passed"] / b["total"] for k, b in buckets.items() if b["total"]}
subs["correctness"] = ev["cases_passed"] / ev["cases_total"]
emit(score, 1, f"{ev['cases_passed']}/{ev['cases_total']} cases, weighted {score:.4f}", subs)
