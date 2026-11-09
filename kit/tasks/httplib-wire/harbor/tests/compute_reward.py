"""tests/compute_reward.py: every scoring decision, then reward.txt, reward.json and details.json on every path.

reward = 0.3 * (upstream tests passed / upstream tests listed)
       + 0.7 * mean over the six areas H, B, Q, M, R, N of (credited cases of the area / cases of the area)
A case is credited when its result equals the frozen expected result byte for byte; a case whose expected result is
a rejection is credited only if some non-rejection case of its family also passes (families without one are exempt).
Hard gates (score 0): httplib.h must compile and link with the two case programs; no test written to fail may pass.
A failed compile of the upstream suite scores that part 0 (not a gate). Denominators are fixed.
"""
import json
from pathlib import Path

OUT = Path("/logs/verifier")
GTEST_WEIGHT = 0.3
AREAS = ["H", "B", "Q", "M", "R", "N"]
NAMES = {"H": "messages", "B": "bodies", "Q": "urls", "M": "multipart", "R": "ranges", "N": "negotiation"}


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
areas = ev.get("areas") or {}
if not ev.get("cases_total") or not ev.get("gtest_total"):
    if ev.get("build_ok"):
        emit(0.0, 0, "evidence has no cases (verifier fault)", {})
if ev.get("cheat_detected") or not ev.get("build_ok"):    # hard gates first
    emit(0.0, 1, ev.get("gate_reason") or "build failed", {"build": 0.0, "upstream_tests": 0.0, "cases": 0.0})
if set(areas) != set(AREAS) or any(not areas[a].get("total") for a in AREAS):
    emit(0.0, 0, "evidence is missing an area (verifier fault)", {})

gt = ev["gtest_passed"] / ev["gtest_total"]
per = {a: areas[a]["credited"] / areas[a]["total"] for a in AREAS}
cases = sum(per.values()) / len(AREAS)
score = GTEST_WEIGHT * gt + (1 - GTEST_WEIGHT) * cases
subs = {"build": 1.0, "upstream_tests": gt, "cases": cases}
for a in AREAS:
    subs[f"area_{NAMES[a]}"] = per[a]
emit(score, 1, f"upstream tests {ev['gtest_passed']}/{ev['gtest_total']}"
     f"{'' if ev.get('gtest_build_ok') else ' (suite did not compile)'}, cases "
     + ", ".join(f"{NAMES[a]} {areas[a]['credited']}/{areas[a]['total']}" for a in AREAS)
     + f", reward {score:.4f}", subs)
