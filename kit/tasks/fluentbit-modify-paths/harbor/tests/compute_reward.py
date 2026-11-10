"""Every scoring decision for the modify-filter task; writes reward.txt, reward.json and details.json.

reward = legacy_factor * sum over buckets b of weight_b * passed_b / total_b
  - hard gates (score exactly 0): deliverable tampering, build failure, any failing upstream test
    (filter_modify runtime suite, record_accessor internal suite)
  - legacy_factor = passed / total of the plain-key regression cases (behaviour that must not change)
"""
import json
from pathlib import Path

OUT = Path("/logs/verifier")


def emit(reward, valid, reason, subscores):
    reward = round(min(1.0, max(0.0, reward)), 6)
    flat = {"reward": reward, "score": reward, "valid": int(valid)}
    flat.update({k: round(float(v), 6) for k, v in subscores.items()})
    (OUT / "reward.json").write_text(json.dumps(flat))
    (OUT / "reward.txt").write_text(f"{reward}\n")
    (OUT / "details.json").write_text(json.dumps({
        "subscores": [{"name": k, "score": round(float(v), 6)} for k, v in subscores.items()],
        "additional_data": {"reason": reason},
    }))
    raise SystemExit(0 if reward > 0 else 1)


def main():
    try:
        ev = json.loads((OUT / "evidence.json").read_text())
    except Exception as e:
        emit(0.0, 0, "no evidence from collect.py: %s" % e, {})
    if not ev.get("runtime_ok", False):
        emit(0.0, 0, "runtime unavailable: " + str(ev.get("runtime_error", "")), {})
    if ev.get("cheat_detected"):
        emit(0.0, 1, "gate: " + str(ev.get("gate_reason", "")), {"build": 0.0, "correctness": 0.0})
    if not ev.get("build_ok"):
        emit(0.0, 1, "gate: " + str(ev.get("gate_reason", "build failed")), {"build": 0.0, "correctness": 0.0})

    weights = ev["weights"]
    buckets = ev.get("buckets", {})
    up = ev.get("upstream", {})
    up_pass = sum(p for p, _ in up.values())
    up_total = sum(t for _, t in up.values())
    upstream = up_pass / up_total if up_total else 0.0

    sub = {"build": 1.0, "upstream_tests": upstream}
    feature = 0.0
    for b, w in weights.items():
        p, t = buckets.get(b, [0, 1])
        frac = p / t if t else 0.0
        sub["bucket_" + b] = frac
        feature += w * frac
    lp, lt = buckets.get("legacy", [0, 1])
    legacy = lp / lt if lt else 0.0
    sub["legacy_factor"] = legacy
    sub["feature_score"] = feature

    if up_total == 0 or up_pass < up_total:
        sub["correctness"] = 0.0
        emit(0.0, 1, "gate: upstream tests failing (%d of %d pass)" % (up_pass, up_total), sub)
    reward = feature * legacy
    sub["correctness"] = reward
    emit(reward, 1, "feature score %.4f x legacy factor %.4f (upstream tests %d/%d)" %
         (feature, legacy, up_pass, up_total), sub)


if __name__ == "__main__":
    main()
