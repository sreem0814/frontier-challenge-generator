"""Smooth dynamics: kinematics, composite inertia, bias forces, passive and actuator forces,
forward and inverse dynamics, Euler and RK4 integration."""
import math

import numpy as np

from . import spatial as sp
from .model import (JNT_FREE, JNT_BALL, JNT_SLIDE, JNT_HINGE, TRN_JOINT, DYN_NONE, DYN_INTEGRATOR,
                    DYN_FILTER, DYN_FILTEREXACT)


# ---------------------------------------------------------------- position stage

def kinematics(m, d):
    d.xpos[0] = 0.0
    d.xquat[0] = [1.0, 0, 0, 0]
    d.xmat[0] = np.eye(3).ravel()
    d.xipos[0] = 0.0
    d.ximat[0] = np.eye(3).ravel()
    for i in range(1, m.nbody):
        jnts = m.body_jnts[i]
        if len(jnts) == 1 and m.jnt_type[jnts[0]] == JNT_FREE:
            j = jnts[0]
            a = m.jnt_qposadr[j]
            xpos = d.qpos[a:a + 3].copy()
            xquat = sp.normalize4(d.qpos[a + 3:a + 7])
            d.xanchor[j] = xpos
            d.xaxis[j] = m.jnt_axis[j]
        else:
            p = m.body_parentid[i]
            if p:
                xpos = d.xpos[p] + d.xmat[p].reshape(3, 3) @ m.body_pos[i]
                xquat = sp.quat_mul(d.xquat[p], m.body_quat[i])
            else:
                xpos = m.body_pos[i].copy()
                xquat = m.body_quat[i].copy()
            for j in jnts:
                a = m.jnt_qposadr[j]
                t = m.jnt_type[j]
                xaxis = sp.rot_vec_quat(m.jnt_axis[j], xquat)
                xanchor = sp.rot_vec_quat(m.jnt_pos[j], xquat) + xpos
                if t == JNT_SLIDE:
                    xpos = xpos + xaxis * (d.qpos[a] - m.qpos0[a])
                else:
                    if t == JNT_BALL:
                        qloc = sp.normalize4(d.qpos[a:a + 4])
                    else:
                        qloc = sp.axis_angle2quat(m.jnt_axis[j], d.qpos[a] - m.qpos0[a])
                    xquat = sp.quat_mul(xquat, qloc)
                    xpos = xanchor - sp.rot_vec_quat(m.jnt_pos[j], xquat)
                d.xanchor[j] = xanchor
                d.xaxis[j] = xaxis
        xquat = sp.normalize4(xquat)
        d.xquat[i] = xquat
        d.xpos[i] = xpos
        R = sp.quat2mat(xquat)
        d.xmat[i] = R.ravel()
        d.xipos[i] = xpos + R @ m.body_ipos[i]
        d.ximat[i] = (R @ sp.quat2mat(m.body_iquat[i])).ravel()
    for s in range(m.nsite):
        b = m.site_bodyid[s]
        R = d.xmat[b].reshape(3, 3)
        d.site_xpos[s] = d.xpos[b] + R @ m.site_pos[s]
        d.site_xmat[s] = (R @ sp.quat2mat(m.site_quat[s])).ravel()
    for g in range(m.ngeom):
        b = m.geom_bodyid[g]
        R = d.xmat[b].reshape(3, 3)
        d.geom_xpos[g] = d.xpos[b] + R @ m.geom_pos[g]
        d.geom_xmat[g] = (R @ sp.quat2mat(m.geom_quat[g])).ravel()


def com_pos(m, d):
    nb = m.nbody
    sub = d.xipos * m.body_mass[:, None]
    for i in range(nb - 1, 0, -1):
        sub[m.body_parentid[i]] += sub[i]
    for i in range(nb):
        if m.body_subtreemass[i] < sp.MINVAL:
            sub[i] = d.xipos[i]
        else:
            sub[i] = sub[i] / m.body_subtreemass[i]
    d.subtree_com = sub
    d.cinert[0] = 0.0
    for i in range(1, nb):
        off = d.xipos[i] - sub[m.body_rootid[i]]
        d.cinert[i] = sp.inert_com(m.body_inertia[i], d.ximat[i].reshape(3, 3), off, m.body_mass[i])
    for i in range(1, nb):
        for j in m.body_jnts[i]:
            da = m.jnt_dofadr[j]
            off = sub[m.body_rootid[i]] - d.xanchor[j]
            t = m.jnt_type[j]
            R = d.xmat[i].reshape(3, 3)
            if t == JNT_FREE:
                for k in range(3):
                    v = np.zeros(6)
                    v[3 + k] = 1.0
                    d.cdof[da + k] = v
                for k in range(3):
                    d.cdof[da + 3 + k] = sp.dof_com(R[:, k], off)
            elif t == JNT_BALL:
                for k in range(3):
                    d.cdof[da + k] = sp.dof_com(R[:, k], off)
            elif t == JNT_SLIDE:
                d.cdof[da] = sp.dof_com(d.xaxis[j], None)
            else:
                d.cdof[da] = sp.dof_com(d.xaxis[j], off)


def tendon(m, d):
    d.ten_J[:] = 0.0
    for i in range(m.ntendon):
        if m.tendon_spatial[i]:
            spatial_tendon(m, d, i)
            continue
        length = 0.0
        for j, coef in m.tendon_joints[i]:
            length += coef * d.qpos[m.jnt_qposadr[j]]
            d.ten_J[i, m.jnt_dofadr[j]] += coef
        d.ten_length[i] = length


def spatial_tendon(m, d, i):
    """Site-to-site path with optional pulleys (no wrapping geoms)."""
    path = m.tendon_path[i]
    divisor = 1.0
    length = 0.0
    J = np.zeros(m.nv)
    j = 0
    while j < len(path) - 1:
        (t0, v0), (t1, v1) = path[j], path[j + 1]
        if t0 == "pulley" or t1 == "pulley":
            if t0 == "pulley":
                divisor = v0
            j += 1
            continue
        p0, p1 = d.site_xpos[v0], d.site_xpos[v1]
        b0, b1 = m.site_bodyid[v0], m.site_bodyid[v1]
        length += float(np.linalg.norm(p1 - p0)) / divisor
        if b0 != b1:
            dif, n = sp.normalize3(p1 - p0)
            jp1, _ = jac(m, d, p1, b1)
            jp0, _ = jac(m, d, p0, b0)
            J += ((jp1 - jp0).T @ dif) / divisor
        j += 1
    d.ten_length[i] = length
    d.ten_J[i] = J


def crb(m, d):
    nv = m.nv
    c = d.cinert.copy()
    for i in range(m.nbody - 1, 0, -1):
        p = m.body_parentid[i]
        if p > 0:
            c[p] += c[i]
    M = np.zeros((nv, nv))
    for i in range(nv):
        M[i, i] = m.dof_armature[i]
        buf = sp.mul_inert_vec(c[m.dof_bodyid[i]], d.cdof[i])
        j = i
        while j >= 0:
            M[i, j] += float(d.cdof[j] @ buf)
            j = m.dof_parentid[j]
    lower = np.tril(M, -1)
    d.qM = lower + lower.T + np.diag(np.diag(M))


def transmission(m, d):
    d.actuator_moment[:] = 0.0
    for i in range(m.nu):
        gear = m.actuator_gear[i]
        tid = m.actuator_trnid[i]
        if m.actuator_trntype[i] == TRN_JOINT:
            d.actuator_length[i] = d.qpos[m.jnt_qposadr[tid]] * gear
            d.actuator_moment[i, m.jnt_dofadr[tid]] = gear
        else:
            d.actuator_length[i] = d.ten_length[tid] * gear
            d.actuator_moment[i] = d.ten_J[tid] * gear


def fwd_position(m, d):
    kinematics(m, d)
    com_pos(m, d)
    tendon(m, d)
    crb(m, d)
    transmission(m, d)


# ---------------------------------------------------------------- velocity stage

def com_vel(m, d):
    d.cvel[0] = 0.0
    for i in range(1, m.nbody):
        cvel = d.cvel[m.body_parentid[i]].copy()
        dofs = m.body_dofs[i]
        k = 0
        while k < len(dofs):
            v = dofs[k]
            t = m.jnt_type[m.dof_jntid[v]]
            if t == JNT_FREE:
                for q in range(3):
                    d.cdof_dot[v + q] = 0.0
                cvel = cvel + d.cdof[v:v + 3].T @ d.qvel[v:v + 3]
                k += 3
                v = dofs[k]
                t = JNT_BALL
            if t == JNT_BALL:
                for q in range(3):
                    d.cdof_dot[v + q] = sp.cross_motion(cvel, d.cdof[v + q])
                cvel = cvel + d.cdof[v:v + 3].T @ d.qvel[v:v + 3]
                k += 3
            else:
                d.cdof_dot[v] = sp.cross_motion(cvel, d.cdof[v])
                cvel = cvel + d.cdof[v] * d.qvel[v]
                k += 1
        d.cvel[i] = cvel


def rne(m, d, flg_acc, qacc=None):
    nb = m.nbody
    cacc = np.zeros((nb, 6))
    if not m.opt.disabled_flag("gravity"):
        cacc[0, 3:] = -m.opt.gravity
    cfrc = np.zeros((nb, 6))
    for i in range(1, nb):
        dofs = m.body_dofs[i]
        a = cacc[m.body_parentid[i]].copy()
        if dofs:
            a = a + d.cdof_dot[dofs].T @ d.qvel[dofs]
            if flg_acc:
                a = a + d.cdof[dofs].T @ qacc[dofs]
        cacc[i] = a
        f = sp.mul_inert_vec(d.cinert[i], a)
        f = f + sp.cross_force(d.cvel[i], sp.mul_inert_vec(d.cinert[i], d.cvel[i]))
        cfrc[i] = f
    for i in range(nb - 1, 0, -1):
        p = m.body_parentid[i]
        if p:
            cfrc[p] += cfrc[i]
    res = np.zeros(m.nv)
    for v in range(m.nv):
        res[v] = float(d.cdof[v] @ cfrc[m.dof_bodyid[v]])
    return res


def poly_force(linear, poly, x, odd):
    x = abs(x) if odd else x
    res = linear
    xp = 1.0
    for p in poly:
        xp *= x
        res += p * xp
    return res


def dpoly_force(linear, poly, x, odd):
    """Derivative of x*poly_force(x) with respect to x."""
    x = abs(x) if odd else x
    res = linear
    xp = 1.0
    for k, p in enumerate(poly):
        xp *= x
        res += (k + 2) * p * xp
    return res


def jac(m, d, point, body):
    """Translational and rotational Jacobians (3 x nv) of a world point attached to body."""
    jp = np.zeros((3, m.nv))
    jr = np.zeros((3, m.nv))
    off = np.asarray(point) - d.subtree_com[m.body_rootid[body]]
    while body and not m.body_dofnum[body]:
        body = m.body_parentid[body]
    if not body:
        return jp, jr
    i = m.body_dofadr[body] + m.body_dofnum[body] - 1
    while i >= 0:
        cd = d.cdof[i]
        jr[:, i] = cd[:3]
        jp[:, i] = cd[3:] + np.cross(cd[:3], off)
        i = m.dof_parentid[i]
    return jp, jr


def apply_ft(m, d, force, torque, point, body, qfrc):
    jp, jr = jac(m, d, point, body)
    qfrc += jp.T @ force + jr.T @ torque


def passive(m, d):
    nv = m.nv
    d.qfrc_spring = np.zeros(nv)
    d.qfrc_damper = np.zeros(nv)
    d.qfrc_gravcomp = np.zeros(nv)
    d.qfrc_passive = np.zeros(nv)
    spring = not m.opt.disabled_flag("spring")
    damper = not m.opt.disabled_flag("damper")
    if not spring and not damper:
        return
    if spring:
        for j in range(m.njnt):
            k = m.jnt_stiffness[j]
            poly = m.jnt_stiffnesspoly[j]
            if k == 0 and not np.any(poly):
                continue
            pa, da = m.jnt_qposadr[j], m.jnt_dofadr[j]
            t = m.jnt_type[j]
            if t == JNT_FREE:
                dif = d.qpos[pa:pa + 3] - m.qpos_spring[pa:pa + 3]
                r = math.sqrt(float(dif @ dif))
                d.qfrc_spring[da:da + 3] += -poly_force(k, poly, r, False) * dif
                pa, da = pa + 3, da + 3
                t = JNT_BALL
            if t == JNT_BALL:
                q = sp.normalize4(d.qpos[pa:pa + 4])
                dif = sp.sub_quat(q, m.qpos_spring[pa:pa + 4])
                r = math.sqrt(float(dif @ dif))
                d.qfrc_spring[da:da + 3] += -poly_force(k, poly, r, False) * dif
            else:
                x = d.qpos[pa] - m.qpos_spring[pa]
                d.qfrc_spring[da] = -x * poly_force(k, poly, x, False)
    if damper:
        for v in range(nv):
            b, poly = m.dof_damping[v], m.dof_dampingpoly[v]
            if b != 0 or np.any(poly):
                d.qfrc_damper[v] = -d.qvel[v] * poly_force(b, poly, d.qvel[v], True)
    for i in range(m.ntendon):
        fs = fd = 0.0
        if spring:
            k, poly = m.tendon_stiffness[i], m.tendon_stiffnesspoly[i]
            if k or np.any(poly):
                L = d.ten_length[i]
                lo, hi = m.tendon_lengthspring[i]
                x = L - hi if L > hi else (L - lo if L < lo else 0.0)
                fs = -x * poly_force(k, poly, x, False)
        if damper:
            b, poly = m.tendon_damping[i], m.tendon_dampingpoly[i]
            if b or np.any(poly):
                v = d.ten_velocity[i]
                fd = -v * poly_force(b, poly, v, True)
        if fs or fd:
            d.qfrc_spring += d.ten_J[i] * fs
            d.qfrc_damper += d.ten_J[i] * fd
    has_gc = False
    g = m.opt.gravity
    if not m.opt.disabled_flag("gravity") and float(g @ g) != 0:
        for i in range(1, m.nbody):
            if m.body_gravcomp[i]:
                has_gc = True
                apply_ft(m, d, -g * (m.body_mass[i] * m.body_gravcomp[i]), np.zeros(3), d.xipos[i], i,
                         d.qfrc_gravcomp)
    d.qfrc_passive = d.qfrc_spring + d.qfrc_damper
    if has_gc:
        d.qfrc_passive = d.qfrc_passive + d.qfrc_gravcomp


def fwd_velocity(m, d):
    d.ten_velocity = d.ten_J @ d.qvel if m.ntendon else np.zeros(0)
    if m.opt.disabled_flag("actuation"):
        d.actuator_velocity = np.zeros(m.nu)
    else:
        d.actuator_velocity = d.actuator_moment @ d.qvel if m.nu else np.zeros(0)
    com_vel(m, d)
    passive(m, d)
    d.qfrc_bias = rne(m, d, False)


# ---------------------------------------------------------------- actuation and acceleration

def next_activation(m, d, i, act_dot):
    adr = m.actuator_actadr[i]
    act = d.act[adr]
    h = m.opt.timestep
    if m.actuator_dyntype[i] == DYN_FILTEREXACT:
        tau = max(sp.MINVAL, m.actuator_dynprm[i, 0])
        act = act + act_dot * tau * (1 - math.exp(-h / tau))
    else:
        act = act + act_dot * h
    if m.actuator_actlimited[i]:
        lo, hi = m.actuator_actrange[i]
        act = min(max(act, lo), hi)
    return act


def fwd_actuation(m, d):
    nu = m.nu
    d.actuator_force = np.zeros(nu)
    d.act_dot = np.zeros(m.na)
    if nu == 0 or m.opt.disabled_flag("actuation"):
        d.qfrc_actuator = np.zeros(m.nv)
        return
    ctrl = np.array(d.ctrl, dtype=float)
    if not m.opt.disabled_flag("clampctrl"):
        for i in range(nu):
            if m.actuator_ctrllimited[i]:
                lo, hi = m.actuator_ctrlrange[i]
                ctrl[i] = min(max(ctrl[i], lo), hi)
    if not np.all(np.isfinite(ctrl)):
        ctrl[:] = 0.0
    for i in range(nu):
        adr = m.actuator_actadr[i]
        if adr < 0:
            continue
        dt = m.actuator_dyntype[i]
        if dt == DYN_INTEGRATOR:
            d.act_dot[adr] = ctrl[i]
        elif dt in (DYN_FILTER, DYN_FILTEREXACT):
            tau = max(sp.MINVAL, m.actuator_dynprm[i, 0])
            d.act_dot[adr] = (ctrl[i] - d.act[adr]) / tau
    force = np.zeros(nu)
    for i in range(nu):
        L, V = d.actuator_length[i], d.actuator_velocity[i]
        gp, bp = m.actuator_gainprm[i], m.actuator_biasprm[i]
        gain = gp[0] if m.actuator_gaintype[i] == 0 else gp[0] + gp[1] * L + gp[2] * V
        adr = m.actuator_actadr[i]
        if adr < 0:
            inp = ctrl[i]
        else:
            inp = next_activation(m, d, i, d.act_dot[adr]) if m.actuator_actearly[i] else d.act[adr]
        f = gain * inp
        if m.actuator_biastype[i] == 1:
            f += bp[0] + bp[1] * L + bp[2] * V
        force[i] = f
    for i in range(nu):
        if m.actuator_forcelimited[i]:
            lo, hi = m.actuator_forcerange[i]
            force[i] = min(max(force[i], lo), hi)
    d.actuator_force = force
    d.qfrc_actuator = d.actuator_moment.T @ force


def xfrc_accumulate(m, d, qfrc):
    for i in range(1, m.nbody):
        f = d.xfrc_applied[i]
        if np.any(f):
            apply_ft(m, d, f[:3], f[3:], d.xipos[i], i, qfrc)


def fwd_acceleration(m, d):
    q = d.qfrc_passive - d.qfrc_bias + d.qfrc_applied + d.qfrc_actuator
    xfrc_accumulate(m, d, q)
    d.qfrc_smooth = q
    d.qacc = np.linalg.solve(d.qM, q) if m.nv else np.zeros(0)


def forward(m, d, sensors=True):
    fwd_position(m, d)
    d.ten_velocity = d.ten_J @ d.qvel if m.ntendon else np.zeros(0)
    d.actuator_velocity = d.actuator_moment @ d.qvel if m.nu else np.zeros(0)
    return  # partial variant: no velocity, force or acceleration stage
    if sensors:
        from . import sensors as sn
        sn.compute(m, d)


def inverse(m, d):
    raise NotImplementedError("inverse dynamics")
    fwd_position(m, d)
    fwd_velocity(m, d)
    d.qfrc_inverse = rne(m, d, False) + d.qM @ d.qacc - d.qfrc_passive


# ---------------------------------------------------------------- integration

def integrate_pos(m, qpos, qvel, h):
    qpos = np.array(qpos, dtype=float)
    for j in range(m.njnt):
        pa, va = m.jnt_qposadr[j], m.jnt_dofadr[j]
        t = m.jnt_type[j]
        if t == JNT_FREE:
            qpos[pa:pa + 3] += h * qvel[va:va + 3]
            pa, va = pa + 3, va + 3
            t = JNT_BALL
        if t == JNT_BALL:
            qpos[pa:pa + 4] = sp.quat_integrate(qpos[pa:pa + 4], qvel[va:va + 3], h)
        else:
            qpos[pa] += h * qvel[va]
    return qpos


def advance(m, d, act_dot, qacc, qvel=None):
    if m.na and not m.opt.disabled_flag("actuation"):
        new = d.act.copy()
        for i in range(m.nu):
            adr = m.actuator_actadr[i]
            if adr >= 0:
                new[adr] = next_activation(m, d, i, act_dot[adr])
        d.act = new
    d.qvel = d.qvel + m.opt.timestep * qacc
    d.qpos = integrate_pos(m, d.qpos, d.qvel if qvel is None else qvel, m.opt.timestep)
    d.time += m.opt.timestep


def euler(m, d):
    h = m.opt.timestep
    implicit = False
    if not m.opt.disabled_flag("eulerdamp") and not m.opt.disabled_flag("damper"):
        for v in range(m.nv):
            if m.dof_damping[v] > 0 or np.any(m.dof_dampingpoly[v]) or m.jnt_hasactuator[m.dof_jntid[v]]:
                implicit = True
                break
    if implicit:
        H = d.qM.copy()
        for v in range(m.nv):
            H[v, v] += h * dpoly_force(m.dof_damping[v], m.dof_dampingpoly[v], d.qvel[v], True)
        qacc = np.linalg.solve(H, d.qfrc_smooth)
    else:
        qacc = d.qacc.copy()
    advance(m, d, d.act_dot.copy(), qacc)


RK4_A = [[0.5, 0, 0], [0, 0.5, 0], [0, 0, 1]]
RK4_B = [1 / 6, 1 / 3, 1 / 3, 1 / 6]


def rk4(m, d):
    nq, nv, na, h = m.nq, m.nv, m.na, m.opt.timestep
    t0 = d.time
    X = [(d.qpos.copy(), d.qvel.copy(), d.act.copy())]
    F = [(d.qacc.copy(), d.act_dot.copy())]
    C = [sum(row[:i + 1]) for i, row in enumerate(RK4_A)]
    for i in range(1, 4):
        dq = np.zeros(nv)
        dv = np.zeros(nv)
        da = np.zeros(na)
        for j in range(i):
            a = RK4_A[i - 1][j]
            dq += a * X[j][1]
            dv += a * F[j][0]
            da += a * F[j][1]
        qpos = integrate_pos(m, X[0][0], dq, h)
        qvel = X[0][1] + h * dv
        act = X[0][2] + h * da
        X.append((qpos, qvel, act))
        d.qpos, d.qvel, d.act = qpos.copy(), qvel.copy(), act.copy()
        d.time = t0 + C[i - 1] * h
        forward(m, d, sensors=False)
        F.append((d.qacc.copy(), d.act_dot.copy()))
    dq = sum(RK4_B[j] * X[j][1] for j in range(4))
    dv = sum(RK4_B[j] * F[j][0] for j in range(4))
    da = sum(RK4_B[j] * F[j][1] for j in range(4)) if na else np.zeros(0)
    d.time = t0
    d.qpos, d.qvel, d.act = X[0][0].copy(), X[0][1].copy(), X[0][2].copy()
    advance(m, d, da, dv, dq)


def step(m, d):
    raise NotImplementedError("integration")
    forward(m, d)
    if m.opt.integrator == "RK4":
        rk4(m, d)
    else:
        euler(m, d)


def mass_matrix(m, d):
    return d.qM.copy()
