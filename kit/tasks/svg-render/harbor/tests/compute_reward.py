"""tests/compute_reward.py: every scoring decision, then reward.txt, reward.json and details.json on every path.

reward = (hidden cases passed) / (hidden cases in the frozen set), after the build and anti-cheat gates.
The reference renderer passes every frozen case, so it scores exactly 1 and the shipped stub scores 0.
"""
import json
import os
from pathlib import Path

OUT = Path("/logs/verifier")
HERE = Path(os.path.dirname(os.path.abspath(__file__)))


def emit(reward, valid, reason, subscores, extra=None):
    reward = round(min(1.0, max(0.0, reward)), 6)
    flat = {"reward": reward, "score": reward, "valid": int(valid)}
    flat.update({k: round(float(v), 6) for k, v in subscores.items()})   # flat, numbers only
    (OUT / "reward.json").write_text(json.dumps(flat))
    (OUT / "reward.txt").write_text(f"{reward}\n")
    data = {"reason": reason}
    data.update(extra or {})
    (OUT / "details.json").write_text(json.dumps({
        "subscores": [{"name": k, "score": v} for k, v in subscores.items()],
        "additional_data": data,
    }, indent=1))
    raise SystemExit(0 if reward > 0 else 1)


def frozen_case_count():
    n = 0
    with open(HERE / "data" / "cases.tsv") as f:
        for line in f:
            if line.strip() and not line.startswith("#"):
                n += 1
    return n


try:
    N = frozen_case_count()
except Exception as e:
    emit(0.0, 0, f"case manifest unreadable: {type(e).__name__}", {})

try:
    ev = json.loads((OUT / "evidence.json").read_text())
except Exception as e:
    emit(0.0, 0, f"no evidence: {type(e).__name__}", {})

if not ev.get("runtime_ok", False):                       # the harness failed, not the agent
    emit(0.0, 0, "runtime unavailable: " + str(ev.get("runtime_error", "")), {})
if ev.get("cases_total") != N or N <= 0:
    emit(0.0, 0, f"evidence covers {ev.get('cases_total')} cases, manifest has {N} (grader fault)", {})

extra = {"build_seconds": ev.get("build_seconds"), "build_log_tail": ev.get("build_log_tail", "")[-1500:],
         "failures": ev.get("failures", [])}
if not ev.get("build_ok"):                                # hard gate: the build
    emit(0.0, 1, ev.get("gate_reason") or "build failed", {"build": 0.0, "correctness": 0.0}, extra)

passed = int(ev.get("cases_passed", 0))
correctness = passed / N                                  # fixed denominator
subs = {"build": 1.0, "correctness": correctness}
for name, b in sorted((ev.get("buckets") or {}).items()):
    if b.get("total"):
        subs[f"bucket_{name}"] = b["passed"] / b["total"]
subs["rendered_fraction"] = int(ev.get("cases_rendered", 0)) / N
if ev.get("cheat_detected"):                              # hard gate: anti-cheat
    subs["anti_cheat"] = 0.0
    emit(0.0, 1, ev.get("gate_reason") or "anti-cheat gate", subs, extra)
subs["anti_cheat"] = 1.0
emit(correctness, 1, f"{passed}/{N} cases match the expected rendering", subs, extra)
