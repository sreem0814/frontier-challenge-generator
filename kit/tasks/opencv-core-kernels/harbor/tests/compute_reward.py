"""tests/compute_reward.py: every scoring decision, then reward.txt, reward.json and details.json on every path.

Score: s = weighted geometric mean over the timed cases of min(s_k, max(S_k, 1)), where s_k is the candidate's
speedup over the shipped build and S_k the optimized upstream build's speedup, both measured in this run.
S = weighted geometric mean of S_k. Each kernel family has equal weight, split equally among its cases.
u = clamp((s - 1 - d) / (S - 1 - d), 0, 1), reward = 2^u - 1.
"""
import json
import math
from pathlib import Path

OUT = Path("/logs/verifier")
HERE = Path(__file__).resolve().parent


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
    cfg = json.loads((HERE / "config.json").read_text())
except Exception as e:
    emit(0.0, 0, f"no evidence: {type(e).__name__}", {})

if not ev.get("runtime_ok", False):                       # the harness failed, not the agent
    emit(0.0, 0, "runtime unavailable: " + str(ev.get("runtime_error", "")), {})

tot = int(ev.get("check_total") or 0)
correct = (tot - int(ev.get("check_failed") or 0)) / tot if tot else 0.0
if ev.get("cheat_detected"):
    emit(0.0, 1, ev.get("gate_reason") or "anti-cheat", {"correctness": 0.0, "build": float(bool(ev.get("build_ok")))})
if not ev.get("build_ok"):
    emit(0.0, 1, ev.get("gate_reason") or "build failed", {"correctness": 0.0, "build": 0.0})
if tot == 0 or ev.get("check_failed"):
    emit(0.0, 1, ev.get("gate_reason") or "correctness gate", {"correctness": correct, "build": 1.0})
if not ev.get("timing_ok"):
    emit(0.0, 1, ev.get("gate_reason") or "timing gate", {"correctness": correct, "build": 1.0, "timing_gate": 0.0})

spec = {c["id"]: c for c in cfg["cases"]}
got = {c["id"]: c for c in ev.get("cases", [])}
if set(got) != set(spec):
    emit(0.0, 0, "timed case set incomplete (verifier fault)", {"correctness": correct})

fams = {}
for cid, c in spec.items():
    fams.setdefault(c["family"], []).append(cid)
weights = {cid: 1.0 / (len(fams) * len(ids)) for ids in fams.values() for cid in ids}

ln_s = ln_S = 0.0
fam_s = {f: 0.0 for f in fams}
fam_S = {f: 0.0 for f in fams}
for cid, w in weights.items():
    s_k, S_k = float(got[cid]["s"]), float(got[cid]["S"])
    if not (s_k > 0 and S_k > 0 and math.isfinite(s_k) and math.isfinite(S_k)):
        emit(0.0, 0, f"timing of {cid} unusable (verifier fault)", {"correctness": correct})
    capped = min(s_k, max(S_k, 1.0))
    ln_s += w * math.log(capped)
    ln_S += w * math.log(S_k)
    n = len(fams[spec[cid]["family"]])
    fam_s[spec[cid]["family"]] += math.log(capped) / n
    fam_S[spec[cid]["family"]] += math.log(S_k) / n

s, S = math.exp(ln_s), math.exp(ln_S)
d = float(cfg["noise_margin"])
if S < float(cfg["min_reference_speedup"]):
    emit(0.0, 0, f"optimized reference build measured only {S:.2f}x here; timing unusable", {"correctness": correct})

u = min(1.0, max(0.0, (s - 1.0 - d) / (S - 1.0 - d)))
reward = 2.0 ** u - 1.0
subs = {"correctness": correct, "build": 1.0, "timing_gate": 1.0, "speedup": s, "reference_speedup": S, "u": u}
for f in sorted(fams):
    subs[f"speedup_{f}"] = math.exp(fam_s[f])
    subs[f"reference_{f}"] = math.exp(fam_S[f])
emit(reward, 1, f"speedup {s:.3f}x of {S:.3f}x reachable (u={u:.3f}); {tot} check records passed", subs)
