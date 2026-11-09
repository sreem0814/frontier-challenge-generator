"""gen/score.py <tests dir> <set.jsonl.gz> <results.json> [<gtest hidden list> <gtest results.json>]
Prints per-area credit and the reward with compute_reward.py's weights."""
import gzip, json, sys
sys.path.insert(0, sys.argv[1])
import wire
GW = 0.3
cases = [json.loads(l) for l in gzip.open(sys.argv[2])]
res = json.load(open(sys.argv[3]))
cred = wire.credit(cases, res)
a = wire.area_scores(cases, cred)
diff = sum(g / t for g, t in a.values()) / len(a)
print({k: f"{g}/{t}={g / t:.3f}" for k, (g, t) in a.items()}, f"diff={diff:.3f}")
if len(sys.argv) > 5:
    hid = [l.strip() for l in open(sys.argv[4]) if l.strip()]
    gr = json.load(open(sys.argv[5]))
    gs = sum(1 for t in hid if gr.get(t) == 0) / len(hid)
    print(f"gtest={gs:.3f} reward={GW * gs + (1 - GW) * diff:.3f}")
