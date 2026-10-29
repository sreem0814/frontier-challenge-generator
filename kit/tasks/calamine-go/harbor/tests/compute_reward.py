"""tests/compute_reward.py: every scoring decision, then reward.txt, reward.json and details.json on every path.

reward = mean over seven buckets (xls, xlsx, xlsb, ods, vba, pictures, objects) of the bucket score, where a
bucket score is the mean, over the hidden workbooks that have units in that bucket, of
(units of that bucket reproduced exactly / units of that bucket in the workbook).
Hard gates (build failure, forbidden constructs, a modified toolchain) score exactly 0.
"""
import json
from pathlib import Path

OUT = Path("/logs/verifier")
BUCKETS = ("xls", "xlsx", "xlsb", "ods", "vba", "pictures", "objects")


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
if ev.get("cheat_detected"):                              # hard gates first
    emit(0.0, 1, ev.get("gate_reason") or "anti-cheat gate", {"build": 0.0, "correctness": 0.0})
if not ev.get("build_ok"):
    emit(0.0, 1, ev.get("gate_reason") or "build failed", {"build": 0.0, "correctness": 0.0})

buckets = ev.get("buckets") or {}
if not ev.get("cases_total") or any((buckets.get(b) or {}).get("files", 0) == 0 for b in BUCKETS):
    emit(0.0, 0, "evidence has no cases for every bucket (verifier fault)", {})

subs = {"build": 1.0}
scores = []
for name in BUCKETS:
    b = buckets[name]
    s = b["score_sum"] / b["files"]          # fixed denominator: every hidden workbook with units in the bucket
    subs[f"bucket_{name}"] = s
    scores.append(s)
reward = sum(scores) / len(scores)
subs["correctness"] = ev["units_passed"] / ev["units_total"] if ev.get("units_total") else 0.0
subs["workbooks_exact"] = ev["cases_passed"] / ev["cases_total"]
reason = (f"{ev['units_passed']}/{ev['units_total']} units, {ev['cases_passed']}/{ev['cases_total']} workbooks exact; "
          + ", ".join(f"{b} {subs['bucket_' + b]:.4f}" for b in BUCKETS))
emit(reward, 1, reason, subs)
