"""Model and Data containers."""
import numpy as np

JNT_FREE, JNT_BALL, JNT_SLIDE, JNT_HINGE = 0, 1, 2, 3
TRN_JOINT, TRN_TENDON = 0, 1
DYN_NONE, DYN_INTEGRATOR, DYN_FILTER, DYN_FILTEREXACT = 0, 1, 2, 3
NQ = {JNT_FREE: 7, JNT_BALL: 4, JNT_SLIDE: 1, JNT_HINGE: 1}
NV = {JNT_FREE: 6, JNT_BALL: 3, JNT_SLIDE: 1, JNT_HINGE: 1}


class Option:
    def __init__(self):
        self.timestep = 0.002
        self.gravity = np.array([0.0, 0.0, -9.81])
        self.integrator = "Euler"
        self.disabled = set()

    def disabled_flag(self, name):
        return name in self.disabled


class Model:
    """Compiled model. Array names follow MuJoCo's mjModel."""

    def finalize(self):
        self.opt_timestep = self.opt.timestep
        self.opt_gravity = self.opt.gravity
        # dof ranges per body for quick access
        self.body_dofs = [list(range(self.body_dofadr[b], self.body_dofadr[b] + self.body_dofnum[b]))
                          if self.body_dofnum[b] else [] for b in range(self.nbody)]
        self.body_jnts = [list(range(self.body_jntadr[b], self.body_jntadr[b] + self.body_jntnum[b]))
                          if self.body_jntnum[b] else [] for b in range(self.nbody)]


class Data:
    """Simulation state and outputs. Array names follow MuJoCo's mjData."""

    def __init__(self, m):
        self.time = 0.0
        self.qpos = m.qpos0.copy()
        self.qvel = np.zeros(m.nv)
        self.act = np.zeros(m.na)
        self.ctrl = np.zeros(m.nu)
        self.qfrc_applied = np.zeros(m.nv)
        self.xfrc_applied = np.zeros((m.nbody, 6))
        self.qacc = np.zeros(m.nv)
        self.act_dot = np.zeros(m.na)
        nb = m.nbody
        self.xpos = np.zeros((nb, 3))
        self.xquat = np.tile([1.0, 0, 0, 0], (nb, 1))
        self.xmat = np.tile(np.eye(3).ravel(), (nb, 1))
        self.xipos = np.zeros((nb, 3))
        self.ximat = np.tile(np.eye(3).ravel(), (nb, 1))
        self.xanchor = np.zeros((m.njnt, 3))
        self.xaxis = np.zeros((m.njnt, 3))
        self.subtree_com = np.zeros((nb, 3))
        self.site_xpos = np.zeros((m.nsite, 3))
        self.site_xmat = np.zeros((m.nsite, 9))
        self.geom_xpos = np.zeros((m.ngeom, 3))
        self.geom_xmat = np.zeros((m.ngeom, 9))
        self.sensordata = np.zeros(m.nsensordata)
        self.subtree_linvel = np.zeros((nb, 3))
        self.subtree_angmom = np.zeros((nb, 3))
        self.cacc = np.zeros((nb, 6))
        self.cfrc_int = np.zeros((nb, 6))
        self.cfrc_ext = np.zeros((nb, 6))
        self.energy = np.zeros(2)
        self.cinert = np.zeros((nb, 10))
        self.cdof = np.zeros((m.nv, 6))
        self.cvel = np.zeros((nb, 6))
        self.cdof_dot = np.zeros((m.nv, 6))
        self.ten_length = np.zeros(m.ntendon)
        self.ten_velocity = np.zeros(m.ntendon)
        self.ten_J = np.zeros((m.ntendon, m.nv))
        self.actuator_length = np.zeros(m.nu)
        self.actuator_velocity = np.zeros(m.nu)
        self.actuator_moment = np.zeros((m.nu, m.nv))
        self.actuator_force = np.zeros(m.nu)
        self.qM = np.zeros((m.nv, m.nv))
        self.qfrc_bias = np.zeros(m.nv)
        self.qfrc_spring = np.zeros(m.nv)
        self.qfrc_damper = np.zeros(m.nv)
        self.qfrc_gravcomp = np.zeros(m.nv)
        self.qfrc_passive = np.zeros(m.nv)
        self.qfrc_actuator = np.zeros(m.nv)
        self.qfrc_smooth = np.zeros(m.nv)
        self.qfrc_inverse = np.zeros(m.nv)
