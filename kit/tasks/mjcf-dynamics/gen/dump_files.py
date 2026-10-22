"""Freeze reference outputs for hand-written models: oracle/bin/python -I dump_files.py <outdir> <xml>..."""
import json, os, sys
import numpy as np
import mujoco as mj
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import oracle_dump as od

out = sys.argv[1]
for sub in ("models", "states", "expected"):
    os.makedirs(os.path.join(out, sub), exist_ok=True)
for i, path in enumerate(sys.argv[2:]):
    xml = open(path).read()
    m = mj.MjModel.from_xml_string(xml)
    d = mj.MjData(m)
    rng = np.random.default_rng(1000 + i)
    nstep = 5
    states, outs = [], []
    for _ in range(3):
        st = od.make_state(m, rng, contacts=od.compile_info(m)['contacts'])
        o, c, w = od.run_state(m, d, st, nstep)
        assert od.ok_numbers(o) and c < od.COND_MAX and not w
        assert not od.robust(m, d, st, o, nstep, rng)
        states.append(st)
        outs.append(o)
    name = os.path.splitext(os.path.basename(path))[0]
    open(os.path.join(out, "models", name + ".xml"), "w").write(xml)
    json.dump({"seed": 1000 + i, "nstep": nstep, "states": states}, open(os.path.join(out, "states", name + ".json"), "w"))
    json.dump({"compile": od.compile_info(m), "states": outs}, open(os.path.join(out, "expected", name + ".json"), "w"))
    print(name, m.nq, m.nv, m.nu, m.nsensordata)
