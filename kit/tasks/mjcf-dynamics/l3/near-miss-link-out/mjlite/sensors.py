"""Sensors, subtree momenta, energy and the post-solve RNE pass (cacc, cfrc_ext, cfrc_int)."""
import math

import numpy as np

from . import spatial as sp
from .model import JNT_FREE, JNT_BALL, TRN_TENDON


def transform_spatial(vec, flg_force, newpos, oldpos, rot=None):
    """Move a spatial vector [rot, lin] from oldpos to newpos; rot (3x3) rotates new -> old frame."""
    vec = np.asarray(vec, float)
    dif = np.asarray(newpos, float) - np.asarray(oldpos, float)
    tran = vec.copy()
    if flg_force:
        tran[:3] = vec[:3] - np.cross(dif, vec[3:])
    else:
        tran[3:] = vec[3:] - np.cross(dif, vec[:3])
    if rot is not None:
        return np.concatenate([rot.T @ tran[:3], rot.T @ tran[3:]])
    return tran


def frame_of(m, d, otype, oid):
    """(body id, world position, world rotation matrix) of an object frame."""
    if otype == "xbody":
        return oid, d.xpos[oid], d.xmat[oid].reshape(3, 3)
    if otype == "body":
        return oid, d.xipos[oid], d.ximat[oid].reshape(3, 3)
    if otype == "site":
        return m.site_bodyid[oid], d.site_xpos[oid], d.site_xmat[oid].reshape(3, 3)
    if otype == "geom":
        return m.geom_bodyid[oid], d.geom_xpos[oid], d.geom_xmat[oid].reshape(3, 3)
    raise ValueError(otype)


def frame_quat(m, d, otype, oid):
    if otype == "xbody":
        return d.xquat[oid].copy()
    if otype == "body":
        return sp.quat_mul(d.xquat[oid], m.body_iquat[oid])
    if otype == "site":
        return sp.quat_mul(d.xquat[m.site_bodyid[oid]], m.site_quat[oid])
    if otype == "geom":
        return sp.quat_mul(d.xquat[m.geom_bodyid[oid]], m.geom_quat[oid])
    raise ValueError(otype)


def object_velocity(m, d, otype, oid, local):
    b, pos, R = frame_of(m, d, otype, oid)
    if m.body_dofnum[m.body_weldid[b]] == 0:
        return np.zeros(6)
    return transform_spatial(d.cvel[b], 0, pos, d.subtree_com[m.body_rootid[b]], R if local else None)


def object_acceleration(m, d, otype, oid, local):
    b, pos, R = frame_of(m, d, otype, oid)
    if m.body_dofnum[m.body_weldid[b]] == 0:
        return np.zeros(6)
    rot = R if local else None
    com = d.subtree_com[m.body_rootid[b]]
    res = transform_spatial(d.cacc[b], 0, pos, com, rot)
    vel = transform_spatial(d.cvel[b], 0, pos, com, rot)
    res[3:] += np.cross(vel[:3], vel[3:])
    return res


def subtree_vel(m, d):
    nb = m.nbody
    body_vel = np.zeros((nb, 6))
    lin = np.zeros((nb, 3))
    ang = np.zeros((nb, 3))
    for i in range(nb):
        body_vel[i] = object_velocity(m, d, "body", i, False)
        lin[i] = body_vel[i, 3:] * m.body_mass[i]
        R = d.ximat[i].reshape(3, 3)
        ang[i] = R @ ((R.T @ body_vel[i, :3]) * m.body_inertia[i])
    for i in range(nb - 1, -1, -1):
        if i:
            lin[m.body_parentid[i]] += lin[i]
        lin[i] = lin[i] / max(sp.MINVAL, m.body_subtreemass[i])
    for i in range(nb - 1, 0, -1):
        p = m.body_parentid[i]
        dx = d.xipos[i] - d.subtree_com[i]
        dv = body_vel[i, 3:] - lin[i]
        ang[i] += np.cross(dx, dv * m.body_mass[i])
        ang[p] += ang[i]
        dx = d.subtree_com[i] - d.subtree_com[p]
        dv = (lin[i] - lin[p]) * m.body_subtreemass[i]
        ang[p] += np.cross(dx, dv)
    d.subtree_linvel = lin
    d.subtree_angmom = ang


def _add_external(m, d, body, point, cfrc, scale):
    if not body:
        return
    com = d.subtree_com[m.body_rootid[body]]
    d.cfrc_ext[body] += scale * transform_spatial(cfrc, 1, com, point)


def tendon_spring_damper(m, d, i):
    from .engine import poly_force
    fs = fd = 0.0
    if not m.opt.disabled_flag("spring"):
        k, poly = m.tendon_stiffness[i], m.tendon_stiffnesspoly[i]
        if k or np.any(poly):
            L = d.ten_length[i]
            lo, hi = m.tendon_lengthspring[i]
            x = L - hi if L > hi else (L - lo if L < lo else 0.0)
            fs = -x * poly_force(k, poly, x, False)
    if not m.opt.disabled_flag("damper"):
        b, poly = m.tendon_damping[i], m.tendon_dampingpoly[i]
        if b or np.any(poly):
            v = d.ten_velocity[i]
            fd = -v * poly_force(b, poly, v, True)
    return fs, fd


def rne_post(m, d):
    nb = m.nbody
    d.cacc = np.zeros((nb, 6))
    if not m.opt.disabled_flag("gravity"):
        d.cacc[0, 3:] = -m.opt.gravity
    d.cfrc_ext = np.zeros((nb, 6))
    for i in range(1, nb):
        f = d.xfrc_applied[i]
        if np.any(f):
            _add_external(m, d, i, d.xipos[i], np.concatenate([f[3:], f[:3]]), 1.0)
    if m.ntendon:
        ten_frc = np.zeros(m.ntendon)
        for a in range(m.nu):
            if m.actuator_trntype[a] == TRN_TENDON:
                ten_frc[m.actuator_trnid[a]] += d.actuator_force[a] * m.actuator_gear[a]
        for t in range(m.ntendon):
            if not m.tendon_spatial[t]:
                continue
            fs, fd = tendon_spring_damper(m, d, t)
            frc = ten_frc[t] + fs + fd
            if not frc:
                continue
            divisor = 1.0
            prevbody, prevpnt = -1, None
            for kind, v in m.tendon_path[t]:
                if kind == "pulley":
                    divisor = v
                    prevbody = -1
                    continue
                body, pnt = m.site_bodyid[v], d.site_xpos[v]
                if prevbody >= 0 and body != prevbody:
                    u, n = sp.normalize3(pnt - prevpnt)
                    if n >= sp.MINVAL:
                        cf = np.concatenate([np.zeros(3), u * (frc / divisor)])
                        _add_external(m, d, body, pnt, cf, 1.0)
                        _add_external(m, d, prevbody, prevpnt, cf, -1.0)
                prevbody, prevpnt = body, pnt
    d.cfrc_int = np.zeros((nb, 6))
    for j in range(1, nb):
        dofs = m.body_dofs[j]
        a = d.cacc[m.body_parentid[j]].copy()
        if dofs:
            a = a + d.cdof_dot[dofs].T @ d.qvel[dofs] + d.cdof[dofs].T @ d.qacc[dofs]
        d.cacc[j] = a
        fb = sp.mul_inert_vec(d.cinert[j], a)
        fb = fb + sp.cross_force(d.cvel[j], sp.mul_inert_vec(d.cinert[j], d.cvel[j]))
        d.cfrc_int[j] = fb - d.cfrc_ext[j]
    for j in range(nb - 1, 0, -1):
        d.cfrc_int[m.body_parentid[j]] += d.cfrc_int[j]


def poly_potential(linear, poly, x):
    res = 0.5 * linear * x * x
    xp = x
    for i, p in enumerate(poly):
        xp *= x
        res += p / (i + 3) * (xp * x)
    return res


def energy_pos(m, d):
    e = 0.0
    if not m.opt.disabled_flag("gravity"):
        for i in range(1, m.nbody):
            e -= m.body_mass[i] * float(m.opt.gravity @ d.xipos[i])
    if not m.opt.disabled_flag("spring"):
        for j in range(m.njnt):
            k, poly = m.jnt_stiffness[j], m.jnt_stiffnesspoly[j]
            if k == 0 and not np.any(poly):
                continue
            pa = m.jnt_qposadr[j]
            t = m.jnt_type[j]
            if t == JNT_FREE:
                x = float(np.linalg.norm(d.qpos[pa:pa + 3] - m.qpos_spring[pa:pa + 3]))
                e += poly_potential(k, poly, x)
                pa += 3
                t = JNT_BALL
            if t == JNT_BALL:
                dif = sp.sub_quat(d.qpos[pa:pa + 4], m.qpos_spring[pa:pa + 4])
                e += poly_potential(k, poly, float(np.linalg.norm(dif)))
            else:
                e += poly_potential(k, poly, d.qpos[pa] - m.qpos_spring[pa])
        for i in range(m.ntendon):
            L = d.ten_length[i]
            lo, hi = m.tendon_lengthspring[i]
            x = L - hi if L > hi else (L - lo if L < lo else 0.0)
            e += poly_potential(m.tendon_stiffness[i], m.tendon_stiffnesspoly[i], x)
    return e


def energy_vel(m, d):
    return 0.5 * float(d.qvel @ (d.qM @ d.qvel))


def compute(m, d):
    """Evaluate every sensor; call after forward dynamics has produced qacc."""
    out = np.zeros(m.nsensordata)
    if not m.nsensor or m.opt.disabled_flag("sensor"):
        d.sensordata = out
        return
    if any(s["type"] in ("subtreelinvel", "subtreeangmom") for s in m.sensors):
        subtree_vel(m, d)
    if any(s["type"] in ("accelerometer", "force", "torque", "framelinacc", "frameangacc")
           for s in m.sensors):
        rne_post(m, d)
    for s in m.sensors:
        t, oid, ot = s["type"], s["objid"], s["objtype"]
        if t == "jointpos":
            v = [d.qpos[m.jnt_qposadr[oid]]]
        elif t == "jointvel":
            v = [d.qvel[m.jnt_dofadr[oid]]]
        elif t == "jointactuatorfrc":
            v = [d.qfrc_actuator[m.jnt_dofadr[oid]]]
        elif t == "ballquat":
            a = m.jnt_qposadr[oid]
            v = sp.normalize4(d.qpos[a:a + 4])
        elif t == "ballangvel":
            a = m.jnt_dofadr[oid]
            v = d.qvel[a:a + 3]
        elif t == "tendonpos":
            v = [d.ten_length[oid]]
        elif t == "tendonvel":
            v = [d.ten_velocity[oid]]
        elif t == "tendonactuatorfrc":
            v = [sum(d.actuator_force[a] for a in range(m.nu)
                     if m.actuator_trntype[a] == TRN_TENDON and m.actuator_trnid[a] == oid)]
        elif t == "actuatorpos":
            v = [d.actuator_length[oid]]
        elif t == "actuatorvel":
            v = [d.actuator_velocity[oid]]
        elif t == "actuatorfrc":
            v = [d.actuator_force[oid]]
        elif t in ("framepos", "framexaxis", "frameyaxis", "framezaxis"):
            _, pos, R = frame_of(m, d, ot, oid)
            vec = pos if t == "framepos" else R[:, "xyz".index(t[5])]
            if s["refid"] >= 0:
                _, rpos, rR = frame_of(m, d, s["reftype"], s["refid"])
                vec = rR.T @ (pos - rpos) if t == "framepos" else rR.T @ vec
            v = vec
        elif t == "framequat":
            q = frame_quat(m, d, ot, oid)
            if s["refid"] >= 0:
                q = sp.quat_mul(sp.quat_neg(frame_quat(m, d, s["reftype"], s["refid"])), q)
            v = q
        elif t in ("framelinvel", "frameangvel"):
            xv = object_velocity(m, d, ot, oid, False)
            if s["refid"] >= 0:
                _, pos, _ = frame_of(m, d, ot, oid)
                _, rpos, rR = frame_of(m, d, s["reftype"], s["refid"])
                rv = object_velocity(m, d, s["reftype"], s["refid"], False)
                rel = xv - rv
                rel[3:] += np.cross(pos - rpos, rv[:3])
                xv = np.concatenate([rR.T @ rel[:3], rR.T @ rel[3:]])
            v = xv[3:] if t == "framelinvel" else xv[:3]
        elif t in ("framelinacc", "frameangacc"):
            xa = object_acceleration(m, d, ot, oid, False)
            v = xa[3:] if t == "framelinacc" else xa[:3]
        elif t == "subtreecom":
            v = d.subtree_com[oid]
        elif t == "subtreelinvel":
            v = d.subtree_linvel[oid]
        elif t == "subtreeangmom":
            v = d.subtree_angmom[oid]
        elif t == "e_potential":
            v = [energy_pos(m, d)]
        elif t == "e_kinetic":
            v = [energy_vel(m, d)]
        elif t == "velocimeter":
            v = object_velocity(m, d, "site", oid, True)[3:]
        elif t == "gyro":
            v = object_velocity(m, d, "site", oid, True)[:3]
        elif t == "accelerometer":
            v = object_acceleration(m, d, "site", oid, True)[3:]
        elif t in ("force", "torque"):
            b = m.site_bodyid[oid]
            f = transform_spatial(d.cfrc_int[b], 1, d.site_xpos[oid], d.subtree_com[m.body_rootid[b]],
                                  d.site_xmat[oid].reshape(3, 3))
            v = f[3:] if t == "force" else f[:3]
        else:
            raise ValueError(t)
        v = np.asarray(v, float)
        c = s["cutoff"]
        if c > 0 and s["datatype"] == "real":
            v = np.clip(v, -c, c)
        out[s["adr"]:s["adr"] + s["dim"]] = v
    d.sensordata = out
