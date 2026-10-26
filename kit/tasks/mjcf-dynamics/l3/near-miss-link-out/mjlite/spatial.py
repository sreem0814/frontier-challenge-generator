"""Quaternion, rotation and spatial-algebra helpers (MuJoCo conventions).

Quaternions are (w, x, y, z). Rotation matrices map local to global. Spatial vectors are
[rotation(3), translation(3)], expressed in the global frame at a reference point (the subtree CoM).
Body inertias in the CoM frame are packed as 10 numbers: Ixx Iyy Izz Ixy Ixz Iyz, m*c (3), m.
"""
import math

import numpy as np

MINVAL = 1e-15
EPS = 1e-14


def normalize3(v):
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if n < MINVAL:
        return np.array([1.0, 0.0, 0.0]), n
    return np.array(v, dtype=float) / n, n


def normalize4(q):
    q = np.asarray(q, dtype=float)
    n = math.sqrt(float(q @ q))
    if n < MINVAL:
        return np.array([1.0, 0.0, 0.0, 0.0])
    return q / n


def quat_mul(a, b):
    return np.array([
        a[0] * b[0] - a[1] * b[1] - a[2] * b[2] - a[3] * b[3],
        a[0] * b[1] + a[1] * b[0] + a[2] * b[3] - a[3] * b[2],
        a[0] * b[2] - a[1] * b[3] + a[2] * b[0] + a[3] * b[1],
        a[0] * b[3] + a[1] * b[2] - a[2] * b[1] + a[3] * b[0],
    ])


def quat_neg(q):
    return np.array([q[0], -q[1], -q[2], -q[3]])


def quat2mat(q):
    w, x, y, z = q
    # exact for unit quaternions; the input is normalized by callers
    return np.array([
        [w * w + x * x - y * y - z * z, 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), w * w - x * x + y * y - z * z, 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), w * w - x * x - y * y + z * z],
    ])


def rot_vec_quat(v, q):
    return quat2mat(q) @ np.asarray(v, dtype=float)


def axis_angle2quat(axis, angle):
    s = math.sin(angle * 0.5)
    return np.array([math.cos(angle * 0.5), axis[0] * s, axis[1] * s, axis[2] * s])


def quat2vel(q, dt):
    axis, sin_a_2 = normalize3(q[1:4])
    if sin_a_2 < MINVAL:
        axis = np.array([1.0, 0.0, 0.0])
    speed = 2 * math.atan2(sin_a_2, q[0])
    if speed > math.pi:
        speed -= 2 * math.pi
    return axis * (speed / dt)


def sub_quat(qa, qb):
    """3D rotation vector taking qb to qa, in qb's local frame."""
    return quat2vel(quat_mul(quat_neg(qb), qa), 1.0)


def quat_integrate(q, vel, scale):
    axis, n = normalize3(vel)
    if n < MINVAL:
        axis = np.array([1.0, 0.0, 0.0])
    qrot = axis_angle2quat(axis, scale * n)
    return quat_mul(normalize4(q), qrot)


def mat2quat(R):
    """Frame (rotation matrix columns) to quaternion, MuJoCo's branch structure."""
    x, y, z = R[:, 0], R[:, 1], R[:, 2]
    mat = (x, y, z)
    q = np.zeros(4)
    if mat[0][0] + mat[1][1] + mat[2][2] > 0:
        q[0] = 0.5 * math.sqrt(1 + mat[0][0] + mat[1][1] + mat[2][2])
        q[1] = 0.25 * (mat[1][2] - mat[2][1]) / q[0]
        q[2] = 0.25 * (mat[2][0] - mat[0][2]) / q[0]
        q[3] = 0.25 * (mat[0][1] - mat[1][0]) / q[0]
    elif mat[0][0] > mat[1][1] and mat[0][0] > mat[2][2]:
        q[1] = 0.5 * math.sqrt(1 + mat[0][0] - mat[1][1] - mat[2][2])
        q[0] = 0.25 * (mat[1][2] - mat[2][1]) / q[1]
        q[2] = 0.25 * (mat[1][0] + mat[0][1]) / q[1]
        q[3] = 0.25 * (mat[2][0] + mat[0][2]) / q[1]
    elif mat[1][1] > mat[2][2]:
        q[2] = 0.5 * math.sqrt(1 - mat[0][0] + mat[1][1] - mat[2][2])
        q[0] = 0.25 * (mat[2][0] - mat[0][2]) / q[2]
        q[1] = 0.25 * (mat[1][0] + mat[0][1]) / q[2]
        q[3] = 0.25 * (mat[2][1] + mat[1][2]) / q[2]
    else:
        q[3] = 0.5 * math.sqrt(1 - mat[0][0] - mat[1][1] + mat[2][2])
        q[0] = 0.25 * (mat[0][1] - mat[1][0]) / q[3]
        q[1] = 0.25 * (mat[2][0] + mat[0][2]) / q[3]
        q[2] = 0.25 * (mat[2][1] + mat[1][2]) / q[3]
    return normalize4(q)


def z2quat(vec):
    """Minimal rotation taking +z to vec."""
    vec = np.asarray(vec, dtype=float)
    c = np.cross([0.0, 0.0, 1.0], vec)
    axis, s = normalize3(c)
    if s < 1e-10:
        axis = np.array([1.0, 0.0, 0.0])
    ang = math.atan2(s, vec[2])
    return np.array([math.cos(ang / 2), *(axis * math.sin(ang / 2))])


def frame_accum(pos, quat, cpos, cquat):
    """Compose parent frame (pos, quat) with child frame (cpos, cquat)."""
    return np.asarray(pos, float) + quat2mat(quat) @ np.asarray(cpos, float), quat_mul(quat, cquat)


# ---------------------------------------------------------------- spatial algebra

def cross_motion(v, u):
    """v x u for motion vectors [w, v]."""
    w, lin = v[:3], v[3:]
    return np.concatenate([np.cross(w, u[:3]), np.cross(w, u[3:]) + np.cross(lin, u[:3])])


def cross_force(v, f):
    """v x* f for a force vector f = [torque, force]."""
    w, lin = v[:3], v[3:]
    return np.concatenate([np.cross(w, f[:3]) + np.cross(lin, f[3:]), np.cross(w, f[3:])])


def inert_com(inertia, R, dif, mass):
    """Body inertia (principal moments, inertial-frame rotation R) mapped to a frame at offset dif."""
    rot = R @ np.diag(inertia) @ R.T
    x, y, z = dif
    res = np.zeros(10)
    res[0] = rot[0, 0] + mass * (y * y + z * z)
    res[1] = rot[1, 1] + mass * (x * x + z * z)
    res[2] = rot[2, 2] + mass * (x * x + y * y)
    res[3] = rot[0, 1] - mass * x * y
    res[4] = rot[0, 2] - mass * x * z
    res[5] = rot[1, 2] - mass * y * z
    res[6:9] = mass * np.asarray(dif)
    res[9] = mass
    return res


def mul_inert_vec(i, v):
    return np.array([
        i[0] * v[0] + i[3] * v[1] + i[4] * v[2] - i[8] * v[4] + i[7] * v[5],
        i[3] * v[0] + i[1] * v[1] + i[5] * v[2] + i[8] * v[3] - i[6] * v[5],
        i[4] * v[0] + i[5] * v[1] + i[2] * v[2] - i[7] * v[3] + i[6] * v[4],
        i[8] * v[1] - i[7] * v[2] + i[9] * v[3],
        i[6] * v[2] - i[8] * v[0] + i[9] * v[4],
        i[7] * v[0] - i[6] * v[1] + i[9] * v[5],
    ])


def dof_com(axis, offset):
    """Motion dof for a hinge (offset given) or a slide (offset None)."""
    if offset is None:
        return np.concatenate([np.zeros(3), axis])
    return np.concatenate([axis, np.cross(axis, offset)])
