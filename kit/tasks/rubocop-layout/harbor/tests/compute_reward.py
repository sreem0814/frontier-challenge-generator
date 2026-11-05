"""tests/compute_reward.py: every scoring decision, then reward.txt, reward.json and details.json on every path.

reward = 0.9 * cop_points / cop_units + 0.1 * dept_passed / dept_units
  cop unit:  0.5 for the exact offense ranges of that cop, +0.5 when the autocorrected source is also exact
  dept unit: 1 when the source after all default-enabled Layout cops autocorrect together is exact
Hard gate (score 0): rubocop must load from the candidate's lib/ with all 100 Layout cops registered.
The frozen set is fixed; errors, crashes and timeouts count as failed units.
"""
import json
from pathlib import Path

OUT = Path("/logs/verifier")
COP_WEIGHT, DEPT_WEIGHT = 0.9, 0.1


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
if not ev.get("cop_units") or not ev.get("dept_units"):
    emit(0.0, 0, "evidence has no cases (verifier fault)", {})
if ev.get("cheat_detected") or not ev.get("build_ok"):    # hard gates first
    emit(0.0, 1, ev.get("gate_reason") or "build failed", {"build": 0.0, "cops": 0.0, "dept": 0.0})

cops = ev["cop_points"] / ev["cop_units"]
dept = ev["dept_passed"] / ev["dept_units"]
score = COP_WEIGHT * cops + DEPT_WEIGHT * dept
subs = {"build": 1.0, "cops": cops, "dept": dept}
for k, b in sorted((ev.get("buckets") or {}).items()):
    if b.get("total"):
        subs[f"bucket_{k}"] = b["points"] / b["total"]
emit(score, 1, f"cop units {ev['cop_points']:.1f}/{ev['cop_units']}, dept {ev['dept_passed']}/{ev['dept_units']}, "
     f"reward {score:.4f}", subs)
