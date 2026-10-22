"""Freeze reference outputs for generated models with MuJoCo 3.16.0 (author side only; needs the pip wheel).

Run with the oracle venv:  oracle/bin/python -I oracle_dump.py <outdir> <first_seed> <count> [--nstate 4]
Writes <outdir>/models/NNNN.xml, <outdir>/states/NNNN.json, <outdir>/expected/NNNN.json.

Version 2 (rework round 1) adds contacts, the constraint pipeline and its robustness filters. A state is kept
only when
  - every output is finite, below 1e7 in magnitude, no contact deeper than 0.08, M is well conditioned and MuJoCo raised no warning;
  - the constraint solution is converged and unique: re-running with 4000 iterations, and with
    the other solver (Newton <-> CG), changes no output by more than 1e-3 of the grading tolerance;
  - it is not at a branch point: 3 perturbations of qpos/qvel by ~1e-7 keep the contact list (count, ordered
    geom pairs, dims) identical and move no output by more than 1e-2 * max(1, max|array|).
Models whose states keep failing are skipped and the next seed is tried (skipped.txt lists them).
"""
import json
import math
import os
import sys

import numpy as np
import mujoco as mj

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_models import Gen  # noqa: E402

COND_MAX = 1e6
BIG = 1e7
MAX_PEN = 0.08
CONTACT_FIELDS = (("geom", 2), ("dist", 1), ("pos", 3), ("frame", 9), ("dim", 1), ("friction", 5),
                  ("solref", 2), ("solimp", 5), ("includemargin", 1))


def quat_slices(m):
    out = []
    for j in range(m.njnt):
        if m.jnt_type[j] == mj.mjtJoint.mjJNT_FREE:
            out.append(int(m.jnt_qposadr[j]) + 3)
        elif m.jnt_type[j] == mj.mjtJoint.mjJNT_BALL:
            out.append(int(m.jnt_qposadr[j]))
    return out


def L(a):
    return [float(x) for x in np.asarray(a, dtype=float).ravel()]


def I(a):
    return [int(x) for x in np.asarray(a).ravel()]


def compile_info(m):
    full = []
    for b in range(m.nbody):
        R = np.zeros(9)
        mj.mju_quat2Mat(R, m.body_iquat[b])
        R = R.reshape(3, 3)
        full.append(R @ np.diag(m.body_inertia[b]) @ R.T)
    return {
        "nq": int(m.nq), "nv": int(m.nv), "nu": int(m.nu), "na": int(m.na), "nbody": int(m.nbody),
        "njnt": int(m.njnt), "nsite": int(m.nsite), "ntendon": int(m.ntendon), "ngeom": int(m.ngeom),
        "neq": int(m.neq),
        "body_parentid": I(m.body_parentid), "jnt_type": I(m.jnt_type), "jnt_bodyid": I(m.jnt_bodyid),
        "jnt_qposadr": I(m.jnt_qposadr), "jnt_dofadr": I(m.jnt_dofadr),
        "dof_bodyid": I(m.dof_bodyid), "dof_parentid": I(m.dof_parentid),
        "geom_type": I(m.geom_type), "geom_bodyid": I(m.geom_bodyid),
        "body_pos": L(m.body_pos), "body_quat": L(m.body_quat), "jnt_pos": L(m.jnt_pos),
        "jnt_axis": L(m.jnt_axis), "geom_pos": L(m.geom_pos), "geom_quat": L(m.geom_quat),
        "geom_size": L(m.geom_size),
        "body_mass": L(m.body_mass), "body_ipos": L(m.body_ipos),
        "body_inertia_full": L(np.array(full)), "qpos0": L(m.qpos0), "qpos_spring": L(m.qpos_spring),
        "dof_armature": L(m.dof_armature), "dof_damping": L(m.dof_damping),
        "jnt_stiffness": L(m.jnt_stiffness), "quat_adr": quat_slices(m),
        "body_invweight0": L(m.body_invweight0), "dof_invweight0": L(m.dof_invweight0),
        "tendon_invweight0": L(m.tendon_invweight0), "actuator_acc0": L(m.actuator_acc0),
        "nsensor": int(m.nsensor), "nsensordata": int(m.nsensordata),
        "sensor_idx": sensor_idx(m),
        "sensor_quat_adr": [int(m.sensor_adr[i]) for i in range(m.nsensor)
                            if m.sensor_datatype[i] == mj.mjtDataType.mjDATATYPE_QUATERNION],
        "constraints": not (m.opt.disableflags & mj.mjtDisableBit.mjDSBL_CONSTRAINT),
        "contacts": not (m.opt.disableflags & (mj.mjtDisableBit.mjDSBL_CONSTRAINT |
                                               mj.mjtDisableBit.mjDSBL_CONTACT)),
    }


def sensor_idx(m):
    out = {"pos": [], "vel": [], "acc": []}
    names = {int(mj.mjtStage.mjSTAGE_POS): "pos", int(mj.mjtStage.mjSTAGE_VEL): "vel",
             int(mj.mjtStage.mjSTAGE_ACC): "acc"}
    for i in range(m.nsensor):
        st = names[int(m.sensor_needstage[i])]
        out[st] += list(range(int(m.sensor_adr[i]), int(m.sensor_adr[i] + m.sensor_dim[i])))
    return out


def rand_quat(rng):
    q = rng.normal(size=4)
    return q / np.linalg.norm(q)


def make_state(m, rng, contacts=False):
    qpos = m.qpos0.copy()
    for j in range(m.njnt):
        a = m.jnt_qposadr[j]
        t = m.jnt_type[j]
        if t == mj.mjtJoint.mjJNT_FREE:
            qpos[a:a + 3] += rng.normal(size=3) * (0.08 if contacts else 0.5)
            qpos[a + 3:a + 7] = rand_quat(rng)
        elif t == mj.mjtJoint.mjJNT_BALL:
            qpos[a:a + 4] = rand_quat(rng)
        elif t == mj.mjtJoint.mjJNT_HINGE:
            qpos[a] += rng.normal() * 0.8
        else:
            qpos[a] += rng.normal() * 0.3
    st = {
        "qpos": L(qpos), "qvel": L(rng.normal(size=m.nv)),
        "act": L(rng.normal(size=m.na) * 0.5), "ctrl": L(rng.uniform(-1.8, 1.8, size=m.nu)),
        "qfrc_applied": L(rng.normal(size=m.nv) if rng.random() < 0.6 else np.zeros(m.nv)),
        "qacc": L(rng.normal(size=m.nv)),
    }
    # muscles and other bounded activations: keep act inside [0, 1] where the dynamics expect it
    for i in range(m.nu):
        if m.actuator_dyntype[i] == mj.mjtDyn.mjDYN_MUSCLE:
            st["act"][int(m.actuator_actadr[i])] = float(rng.uniform(0, 1))
            st["ctrl"][i] = float(rng.uniform(-0.2, 1.2))
    if contacts and rng.random() < 0.85:
        settle(m, st, rng)
    xf = np.zeros((m.nbody, 6))
    if m.nbody > 1 and rng.random() < 0.5:
        for b in rng.choice(np.arange(1, m.nbody), size=min(2, m.nbody - 1), replace=False):
            xf[b] = rng.normal(size=6)
    st["xfrc_applied"] = L(xf)
    return st


def settle(m, st, rng):
    """Let the model fall into contact for a short while (from rest), then add a velocity kick, so that
    contact states look like a running simulation: many shallow contacts instead of deep overlaps."""
    d = mj.MjData(m)
    d.qpos[:] = st["qpos"]
    if m.na:
        d.act[:] = st["act"]
    if m.nu:
        d.ctrl[:] = st["ctrl"]
    saved = (m.opt.tolerance, m.opt.iterations)
    m.opt.tolerance, m.opt.iterations = 1e-8, 100     # a plausible start state only; not graded
    try:
        for _ in range(int(rng.integers(30, 400))):
            mj.mj_step(m, d)
    finally:
        m.opt.tolerance, m.opt.iterations = saved
    if not (np.all(np.isfinite(d.qpos)) and np.all(np.isfinite(d.qvel))):
        return
    st["qpos"] = L(d.qpos)
    st["qvel"] = L(d.qvel + rng.normal(size=m.nv) * 0.5)
    if m.na:
        st["act"] = L(d.act)


def perturb(m, st, rng, eps=1e-7):
    s = json.loads(json.dumps(st))
    q = np.array(s["qpos"]) + rng.normal(size=m.nq) * eps
    for a in quat_slices(m):
        q[a:a + 4] /= np.linalg.norm(q[a:a + 4])
    s["qpos"] = L(q)
    s["qvel"] = L(np.array(s["qvel"]) + rng.normal(size=m.nv) * eps)
    return s


def set_state(m, d, st):
    mj.mj_resetData(m, d)
    d.qpos[:] = st["qpos"]
    d.qvel[:] = st["qvel"]
    if m.na:
        d.act[:] = st["act"]
    if m.nu:
        d.ctrl[:] = st["ctrl"]
    d.qfrc_applied[:] = st["qfrc_applied"]
    d.xfrc_applied[:] = np.array(st["xfrc_applied"]).reshape(m.nbody, 6)


def contacts(d):
    n = int(d.ncon)
    out = {"ncon": n}
    for f, k in CONTACT_FIELDS:
        a = np.asarray(getattr(d.contact, f))[:n]
        out["con_" + f] = I(a) if f in ("geom", "dim") else L(a)
    return out


def run_state(m, d, st, nstep):
    out = {}
    set_state(m, d, st)
    mj.mj_forward(m, d)
    warn = int(d.warning.number.sum())
    M = np.zeros((m.nv, m.nv))
    mj.mj_fullM(m, d, M)
    out.update({
        "xpos": L(d.xpos), "xmat": L(d.xmat), "xipos": L(d.xipos), "subtree_com": L(d.subtree_com),
        "site_xpos": L(d.site_xpos), "site_xmat": L(d.site_xmat),
        "ten_length": L(d.ten_length), "ten_velocity": L(d.ten_velocity),
        "actuator_length": L(d.actuator_length), "actuator_velocity": L(d.actuator_velocity),
        "M": L(M), "qfrc_bias": L(d.qfrc_bias), "qfrc_passive": L(d.qfrc_passive),
        "actuator_force": L(d.actuator_force), "qfrc_actuator": L(d.qfrc_actuator),
        "act_dot": L(d.act_dot), "qacc": L(d.qacc), "sensordata": L(d.sensordata),
        "qfrc_constraint": L(d.qfrc_constraint),
        "efc_counts": [int(d.ne), int(d.nf), int(d.nl), int(d.nefc)],
    })
    out.update(contacts(d))
    cond = float(np.linalg.cond(M)) if m.nv else 1.0
    set_state(m, d, st)
    d.qacc[:] = st["qacc"]
    mj.mj_inverse(m, d)
    out["qfrc_inverse"] = L(d.qfrc_inverse)
    warn += int(d.warning.number.sum())
    set_state(m, d, st)
    for _ in range(nstep):
        mj.mj_step(m, d)
        warn += int(d.warning.number.sum())
    out["step_qpos"] = L(d.qpos)
    out["step_qvel"] = L(d.qvel)
    out["step_act"] = L(d.act)
    return out, cond, warn


FLOATS = None


def float_keys(o):
    return [k for k, v in o.items() if isinstance(v, list) and k not in ("efc_counts", "con_geom", "con_dim")]


def ok_numbers(out):
    for k in float_keys(out):
        v = out[k]
        if not all(math.isfinite(x) for x in v):
            return False
        if v and max(abs(x) for x in v) > BIG:
            return False
    return True


def same_within(a, b, frac_tol):
    """max element error of b vs a, as a fraction of the grading tolerance (contact arrays matched by order)."""
    worst = 0.0
    for k in float_keys(a):
        x, y = np.array(a[k]), np.array(b.get(k, []))
        if x.shape != y.shape:
            return False
        if x.size == 0:
            continue
        tol = 1e-6 * np.abs(x) + 1e-8 * np.abs(x).max() + 1e-10
        worst = max(worst, float((np.abs(x - y) / tol).max()))
    return worst <= frac_tol


def contact_key(o):
    return (o["ncon"], tuple(o["con_geom"]), tuple(o["con_dim"]), tuple(o["efc_counts"]))


def robust(m, d, st, base, nstep, rng):
    """Convergence/uniqueness and branch-point filters; returns '' when the state is kept."""
    if not (m.opt.disableflags & mj.mjtDisableBit.mjDSBL_CONSTRAINT):
        saved = (m.opt.tolerance, m.opt.iterations, m.opt.solver)
        try:
            m.opt.tolerance, m.opt.iterations = 0.0, 4000
            tight, _, _ = run_state(m, d, st, nstep)
            m.opt.solver = (mj.mjtSolver.mjSOL_CG if saved[2] == mj.mjtSolver.mjSOL_NEWTON
                            else mj.mjtSolver.mjSOL_NEWTON)
            other, _, _ = run_state(m, d, st, nstep)
        finally:
            m.opt.tolerance, m.opt.iterations, m.opt.solver = saved
        for alt, name in ((tight, "tight"), (other, "other solver")):
            if contact_key(alt) != contact_key(base) or not same_within(base, alt, 1e-3):
                return "not converged/unique (" + name + ")"
    for _ in range(3):
        ps = perturb(m, st, rng)
        po, _, _ = run_state(m, d, ps, nstep)
        if contact_key(po) != contact_key(base):
            return "contact set changes under 1e-7 perturbation"
        for k in float_keys(base):
            x, y = np.array(base[k]), np.array(po[k])
            if x.size and np.abs(x - y).max() > 1e-2 * max(1.0, np.abs(x).max()):
                return f"jump in {k} under 1e-7 perturbation"
    return ""


def main():
    outdir, first, count = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    nstate = int(sys.argv[sys.argv.index("--nstate") + 1]) if "--nstate" in sys.argv else 4
    for sub in ("models", "states", "expected"):
        os.makedirs(os.path.join(outdir, sub), exist_ok=True)
    skipped, fams = [], {}
    seed, made = first, 0
    while made < count:
        g = Gen(seed)
        xml = g.build()
        try:
            m = mj.MjModel.from_xml_string(xml)
        except Exception as e:
            skipped.append(f"{seed} compile: {e}".replace("\n", " "))
            seed += 1
            continue
        if m.nv == 0:
            skipped.append(f"{seed} no dofs")
            seed += 1
            continue
        d = mj.MjData(m)
        rng = np.random.default_rng(seed)
        nstep = int(rng.integers(3, 11))
        cinfo = compile_info(m)
        states, outs, reasons = [], [], []
        tries = 0
        while len(states) < nstate and tries < 4 * nstate:
            tries += 1
            st = make_state(m, rng, contacts=cinfo["contacts"])
            o, c, w = run_state(m, d, st, nstep)
            if not ok_numbers(o):
                reasons.append("magnitude")
                continue
            if o["con_dist"] and min(o["con_dist"]) < -MAX_PEN:
                reasons.append("deep penetration")
                continue
            if c > COND_MAX:
                reasons.append("cond")
                continue
            if w:
                reasons.append("warning")
                continue
            why = robust(m, d, st, o, nstep, rng)
            if why:
                reasons.append(why)
                continue
            states.append(st)
            outs.append(o)
        if len(states) < nstate:
            skipped.append(f"{seed} {g.fam}: " + "; ".join(sorted(set(reasons))))
            seed += 1
            continue
        name = f"{made:04d}"
        with open(os.path.join(outdir, "models", name + ".xml"), "w") as f:
            f.write(xml)
        with open(os.path.join(outdir, "states", name + ".json"), "w") as f:
            json.dump({"seed": seed, "nstep": nstep, "states": states}, f)
        cinfo["family"] = g.fam
        with open(os.path.join(outdir, "expected", name + ".json"), "w") as f:
            json.dump({"compile": cinfo, "states": outs}, f)
        fams[g.fam] = fams.get(g.fam, 0) + 1
        made += 1
        seed += 1
        if made % 20 == 0:
            print(f"made {made} (seed {seed})", flush=True)
    with open(os.path.join(outdir, "skipped.txt"), "w") as f:
        f.write("\n".join(skipped) + "\n")
    print(f"made {made}, skipped {len(skipped)}, last seed {seed - 1}, families {fams}")


if __name__ == "__main__":
    main()
