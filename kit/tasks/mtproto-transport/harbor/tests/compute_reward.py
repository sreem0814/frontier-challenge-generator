"""tests/compute_reward.py: every scoring decision, then reward.txt, reward.json and details.json on every path.

reward = sum over buckets of weight * passed / total, with the weights below summing to 1. The reference solution
passes every case, so it scores 1; the untouched base fails every case and scores 0. Any hard gate scores 0.
"""
import json
from pathlib import Path

OUT = Path("/logs/verifier")
WEIGHTS = {
    "codec": 0.06,        # proto/codec framing
    "obfs": 0.06,         # mtproxy/obfuscated2
    "msg": 0.14,          # MTProto 2.0 / 1.0 message crypto
    "hs": 0.12,           # key-exchange primitives (RSA_PAD, pq, DH checks, temp keys)
    "kex": 0.22,          # exchange client and server flows
    "sess": 0.32,         # mtproto session layer, rpc engine, salts
    "integration": 0.08,  # the module's own tests that run through these packages
}


def emit(reward, valid, reason, subscores, extra=None):
    reward = round(min(1.0, max(0.0, reward)), 6)
    flat = {"reward": reward, "score": reward, "valid": int(valid)}
    flat.update({k: round(float(v), 6) for k, v in subscores.items()})   # flat, numbers only
    (OUT / "reward.json").write_text(json.dumps(flat))
    (OUT / "reward.txt").write_text(f"{reward}\n")
    details = {
        "subscores": [{"name": k, "score": v} for k, v in subscores.items()],
        "additional_data": {"reason": reason},
    }
    if extra:
        details["additional_data"].update(extra)
    (OUT / "details.json").write_text(json.dumps(details))
    raise SystemExit(0 if reward > 0 else 1)


try:
    ev = json.loads((OUT / "evidence.json").read_text())
except Exception as e:
    emit(0.0, 0, f"no evidence: {type(e).__name__}", {})

if not ev.get("runtime_ok", False):                       # the harness failed, not the agent
    emit(0.0, 0, "runtime unavailable: " + str(ev.get("runtime_error", "")), {})

build_sub = ev.get("build_packages_ok", 0) / max(1, ev.get("build_packages_total", 4))
if ev.get("cheat_detected"):
    emit(0.0, 1, "anti-cheat: " + str(ev.get("gate_reason", "")),
         {"anticheat": 0.0, "build": build_sub, "correctness": 0.0}, {"notes": ev.get("notes", [])[:5]})
if ev.get("gate_failed") or not ev.get("build_ok"):
    emit(0.0, 1, "gate: " + str(ev.get("gate_reason") or "build failed"),
         {"anticheat": 1.0, "build": build_sub, "correctness": 0.0}, {"notes": ev.get("notes", [])[:5]})

buckets = ev.get("buckets") or {}
if set(buckets) != set(WEIGHTS) or any(not buckets[k].get("total") for k in WEIGHTS):
    emit(0.0, 0, "evidence is missing case buckets (verifier fault): " + ",".join(sorted(buckets)), {})

subs = {"anticheat": 1.0, "build": 1.0}
score = 0.0
for k, w in WEIGHTS.items():
    frac = buckets[k]["passed"] / buckets[k]["total"]
    subs[f"bucket_{k}"] = frac
    score += w * frac
subs["correctness"] = ev["cases_passed"] / ev["cases_total"]
reason = f"{ev['cases_passed']}/{ev['cases_total']} cases; weighted {score:.4f}; " + ", ".join(
    f"{k} {buckets[k]['passed']}/{buckets[k]['total']}" for k in WEIGHTS)
emit(score, 1, reason, subs, {"failed_cases": ev.get("failed_cases", [])[:60]})
