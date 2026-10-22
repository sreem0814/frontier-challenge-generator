"""Case definitions and tolerance checks. Standard library only (the verifier runs with python3 -I -S).

grade_model(expected, got) returns a list of (bucket, passed) pairs whose length depends only on the
expected data, so the denominator is fixed whatever the candidate produced.
"""
import math

RTOL = 1e-6        # relative to each expected component
ATOL_REL = 1e-8    # relative to the largest expected magnitude in the array
ATOL = 1e-10       # absolute floor

WEIGHTS = {
    "tree": 1, "frames": 1, "inertia": 1, "dofs": 1, "invweight": 3,
    "kin_body": 1, "kin_com": 1, "kin_site": 1, "mass": 1, "bias": 1,
    "transmission": 4, "passive": 4, "actuation": 4,
    "contacts": 16, "efc_rows": 5, "constraint": 12, "accel": 12, "inverse": 10, "step": 13,
    "sensor_pos": 2, "sensor_vel": 2, "sensor_acc": 4,
}

CONTACT_FIELDS = (("dist", 1), ("pos", 3), ("frame", 9), ("friction", 5), ("solref", 2), ("solimp", 5),
                  ("includemargin", 1))


def num(x):
    return not isinstance(x, bool) and isinstance(x, (int, float)) and math.isfinite(x)


def close(got, exp, quats=()):
    """got, exp: flat lists. quats: start indices of 4-blocks compared up to sign."""
    if not isinstance(got, list) or len(got) != len(exp):
        return False
    scale = max((abs(x) for x in exp), default=0.0)
    qset = set()
    for a in quats:
        qset.update(range(a, a + 4))

    def ok(i, sign=1.0):
        x, y = got[i], exp[i]
        if not num(x):
            return False
        return abs(x * sign - y) <= RTOL * abs(y) + ATOL_REL * scale + ATOL

    for i in range(len(exp)):
        if i in qset:
            continue
        if not ok(i):
            return False
    for a in quats:
        if not (all(ok(i) for i in range(a, a + 4)) or all(ok(i, -1.0) for i in range(a, a + 4))):
            return False
    return True


def quat2mat(q):
    n = math.sqrt(sum(x * x for x in q)) or 1.0
    w, x, y, z = (v / n for v in q)
    return [[w * w + x * x - y * y - z * z, 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), w * w - x * x + y * y - z * z, 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), w * w - x * x - y * y + z * z]]


def inertia_full(iquat, inertia, nbody):
    """Body inertia tensors (about the CoM, body frame) from principal frame and moments, flattened."""
    if not isinstance(iquat, list) or not isinstance(inertia, list):
        return None
    if len(iquat) != 4 * nbody or len(inertia) != 3 * nbody:
        return None
    if not all(num(x) for x in iquat + inertia):
        return None
    out = []
    for b in range(nbody):
        R = quat2mat(iquat[4 * b:4 * b + 4])
        I = inertia[3 * b:3 * b + 3]
        for i in range(3):
            for j in range(3):
                out.append(sum(R[i][k] * I[k] * R[j][k] for k in range(3)))
    return out


def all_close(got, exp, keys, quats=None):
    quats = quats or {}
    for k in keys:
        if not close(got.get(k) if isinstance(got, dict) else None, exp[k], quats.get(k, ())):
            return False
    return True


def contacts_match(gs, es):
    """The contact list matches as a set: same count, and a one-to-one pairing of contacts with the same
    ordered geom pair and dim whose float fields all pass the tolerance (scale per field over all contacts)."""
    n = es["ncon"]
    if gs.get("ncon") != n or isinstance(gs.get("ncon"), bool):
        return False
    if n == 0:
        return True
    geom, dim = gs.get("con_geom"), gs.get("con_dim")
    if not isinstance(geom, list) or len(geom) != 2 * n or not isinstance(dim, list) or len(dim) != n:
        return False
    fields = {}
    for f, k in CONTACT_FIELDS:
        g = gs.get("con_" + f)
        if not isinstance(g, list) or len(g) != k * n or not all(num(x) for x in g):
            return False
        e = es["con_" + f]
        scale = max((abs(x) for x in e), default=0.0)
        fields[f] = (k, g, e, scale)

    def same(i, j):
        if geom[2 * j] != es["con_geom"][2 * i] or geom[2 * j + 1] != es["con_geom"][2 * i + 1]:
            return False
        if dim[j] != es["con_dim"][i]:
            return False
        for f, (k, g, e, scale) in fields.items():
            for c in range(k):
                y, x = e[k * i + c], g[k * j + c]
                if abs(x - y) > RTOL * abs(y) + ATOL_REL * scale + ATOL:
                    return False
        return True

    used = [False] * n
    for i in range(n):
        for j in range(n):
            if not used[j] and same(i, j):
                used[j] = True
                break
        else:
            return False
    return True


TREE_INTS = ("nq", "nv", "nu", "na", "nbody", "njnt", "nsite", "ntendon", "ngeom", "neq")
TREE_LISTS = ("body_parentid", "jnt_type", "jnt_bodyid", "jnt_qposadr", "jnt_dofadr", "dof_bodyid",
              "dof_parentid", "geom_type", "geom_bodyid")


def grade_model(exp, got):
    """Cases of one model; any malformed candidate output fails the affected cases, never the grader."""
    try:
        return _grade_model(exp, got)
    except Exception:
        return [(b, False) for b, _ in _grade_model(exp, None)]


def _grade_model(exp, got):
    if not isinstance(got, dict):
        got = None
    ce = exp["compile"]
    gc = (got or {}).get("compile")
    gc = gc if isinstance(gc, dict) else {}
    res = []
    tree = all(gc.get(k) == ce[k] for k in TREE_INTS) and all(gc.get(k) == ce[k] for k in TREE_LISTS)
    res.append(("tree", tree))
    nb = ce["nbody"]
    bq = list(range(0, 4 * nb, 4))
    gq = list(range(0, 4 * ce["ngeom"], 4))
    res.append(("frames", all_close(gc, ce, ("body_pos", "body_quat", "jnt_pos", "jnt_axis", "geom_pos",
                                             "geom_quat", "geom_size"), {"body_quat": bq, "geom_quat": gq})))
    full = None
    try:
        full = inertia_full(gc.get("body_iquat"), gc.get("body_inertia"), nb)
    except Exception:
        full = None
    res.append(("inertia", all_close(gc, ce, ("body_mass", "body_ipos")) and close(full, ce["body_inertia_full"])))
    qa = ce["quat_adr"]
    res.append(("dofs", all_close(gc, ce, ("qpos0", "qpos_spring", "dof_armature", "dof_damping",
                                           "jnt_stiffness"), {"qpos0": qa, "qpos_spring": qa})))
    res.append(("invweight", all_close(gc, ce, ("body_invweight0", "dof_invweight0", "tendon_invweight0",
                                                "actuator_acc0"))))
    gstates = (got or {}).get("states")
    gstates = gstates if isinstance(gstates, list) else []
    for s, es in enumerate(exp["states"]):
        gs = gstates[s] if s < len(gstates) and isinstance(gstates[s], dict) else {}
        res.append(("kin_body", all_close(gs, es, ("xpos", "xmat"))))
        res.append(("kin_com", all_close(gs, es, ("xipos", "subtree_com"))))
        if ce["nsite"]:
            res.append(("kin_site", all_close(gs, es, ("site_xpos", "site_xmat"))))
        if ce["ntendon"] or ce["nu"]:
            res.append(("transmission", all_close(gs, es, ("ten_length", "ten_velocity", "actuator_length",
                                                           "actuator_velocity"))))
        res.append(("mass", all_close(gs, es, ("M",))))
        res.append(("bias", all_close(gs, es, ("qfrc_bias",))))
        res.append(("passive", all_close(gs, es, ("qfrc_passive",))))
        if ce["nu"]:
            res.append(("actuation", all_close(gs, es, ("actuator_force", "qfrc_actuator", "act_dot"))))
        if ce["contacts"]:
            res.append(("contacts", contacts_match(gs, es)))
        if ce["constraints"]:
            res.append(("efc_rows", gs.get("efc_counts") == es["efc_counts"]))
            res.append(("constraint", all_close(gs, es, ("qfrc_constraint",))))
        res.append(("accel", all_close(gs, es, ("qacc",))))
        res.append(("inverse", all_close(gs, es, ("qfrc_inverse",))))
        res.append(("step", all_close(gs, es, ("step_qpos", "step_qvel", "step_act"), {"step_qpos": qa})))
        sd = gs.get("sensordata")
        for stage in ("pos", "vel", "acc"):
            idx = ce["sensor_idx"][stage]
            if not idx:
                continue
            exp_sub = [es["sensordata"][i] for i in idx]
            got_sub = [sd[i] for i in idx] if isinstance(sd, list) and len(sd) == len(es["sensordata"]) else None
            quats = [idx.index(a) for a in ce["sensor_quat_adr"] if a in idx]
            res.append(("sensor_" + stage, close(got_sub, exp_sub, quats)))
    return res
