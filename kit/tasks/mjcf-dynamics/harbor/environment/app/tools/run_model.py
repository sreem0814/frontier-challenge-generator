"""Runs one model through the candidate package and records its outputs as JSON.

Executed by the verifier as an unprivileged user, once per model:
    python3 -I driver.py <package parent dir> <model.xml> <states.json> <out.json>
It never sees reference outputs. Every phase is isolated: an exception in one phase is recorded and the
remaining phases still run. The output file is replaced atomically after each phase.
"""
import json
import os
import sys
import traceback

PKG_PARENT, MODEL, STATES, OUT = sys.argv[1:5]
sys.path.insert(0, PKG_PARENT)
_stdout = sys.stdout
sys.stdout = sys.stderr          # candidate prints never reach our output

import numpy as np  # noqa: E402

result = {"compile": None, "compile_error": "", "states": []}


def save():
    tmp = OUT + ".tmp"
    with open(tmp, "w") as f:
        json.dump(result, f)
    os.replace(tmp, OUT)


def err():
    return traceback.format_exc(limit=3)[-600:]


def vec(x):
    try:
        a = np.asarray(x, dtype=float).ravel()
        return [float(v) for v in a]
    except Exception:
        return None


def ints(x):
    try:
        a = np.asarray(x).ravel()
        return [int(v) for v in a]
    except Exception:
        return None


def get(obj, name, conv):
    try:
        return conv(getattr(obj, name))
    except Exception:
        return None


try:
    import mjlite
    m = mjlite.load_model(MODEL)
    c = {}
    for k in ("nq", "nv", "nu", "na", "nbody", "njnt", "nsite", "ntendon", "ngeom", "neq"):
        c[k] = get(m, k, int)
    for k in ("body_parentid", "jnt_type", "jnt_bodyid", "jnt_qposadr", "jnt_dofadr", "dof_bodyid",
              "dof_parentid", "geom_type", "geom_bodyid"):
        c[k] = get(m, k, ints)
    for k in ("body_pos", "body_quat", "jnt_pos", "jnt_axis", "geom_pos", "geom_quat", "geom_size",
              "body_mass", "body_ipos", "body_iquat", "body_inertia", "qpos0", "qpos_spring", "dof_armature",
              "dof_damping", "jnt_stiffness", "body_invweight0", "dof_invweight0", "tendon_invweight0",
              "actuator_acc0"):
        c[k] = get(m, k, vec)
    result["compile"] = c
except Exception:
    result["compile_error"] = err()
    save()
    sys.exit(0)
save()

with open(STATES) as f:
    spec = json.load(f)
nstep = int(spec["nstep"])


def fresh(st):
    d = mjlite.Data(m)
    d.qpos[:] = st["qpos"]
    d.qvel[:] = st["qvel"]
    if len(st["act"]):
        d.act[:] = st["act"]
    if len(st["ctrl"]):
        d.ctrl[:] = st["ctrl"]
    d.qfrc_applied[:] = st["qfrc_applied"]
    d.xfrc_applied[:] = np.asarray(st["xfrc_applied"], dtype=float).reshape(np.shape(d.xfrc_applied))
    return d


FWD = ("xpos", "xmat", "xipos", "subtree_com", "site_xpos", "site_xmat", "ten_length", "ten_velocity",
       "actuator_length", "actuator_velocity", "qfrc_bias", "qfrc_passive", "actuator_force",
       "qfrc_actuator", "act_dot", "qacc", "sensordata", "qfrc_constraint")
CONTACT = (("geom", 2, ints), ("dim", 1, ints), ("dist", 1, vec), ("pos", 3, vec), ("frame", 9, vec),
           ("friction", 5, vec), ("solref", 2, vec), ("solimp", 5, vec), ("includemargin", 1, vec))


def contacts(d, out):
    """d.ncon and the first ncon entries of each d.contact field (MuJoCo layout: geom (ncon, 2) etc.)."""
    try:
        n = int(d.ncon)
        out["ncon"] = n
    except Exception:
        return
    for f, k, conv in CONTACT:
        try:
            a = conv(getattr(d.contact, f))
            out["con_" + f] = a[:k * n] if a is not None and len(a) >= k * n else None
        except Exception:
            out["con_" + f] = None
    try:
        out["efc_counts"] = [int(d.ne), int(d.nf), int(d.nl), int(d.nefc)]
    except Exception:
        out["efc_counts"] = None


for st in spec["states"]:
    out = {"errors": []}
    try:
        d = fresh(st)
        mjlite.forward(m, d)
        for k in FWD:
            out[k] = get(d, k, vec)
        contacts(d, out)
        try:
            out["M"] = vec(mjlite.mass_matrix(m, d))
        except Exception:
            out["errors"].append("mass_matrix: " + err())
    except Exception:
        out["errors"].append("forward: " + err())
    result["states"].append(out)
    save()
    try:
        d = fresh(st)
        d.qacc[:] = st["qacc"]
        mjlite.inverse(m, d)
        out["qfrc_inverse"] = get(d, "qfrc_inverse", vec)
    except Exception:
        out["errors"].append("inverse: " + err())
    save()
    try:
        d = fresh(st)
        for _ in range(nstep):
            mjlite.step(m, d)
        out["step_qpos"] = get(d, "qpos", vec)
        out["step_qvel"] = get(d, "qvel", vec)
        out["step_act"] = get(d, "act", vec)
    except Exception:
        out["errors"].append("step: " + err())
    save()
sys.stdout = _stdout
