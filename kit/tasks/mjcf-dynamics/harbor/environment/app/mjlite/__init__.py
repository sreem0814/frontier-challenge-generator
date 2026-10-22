"""mjlite: a Python/NumPy port of MuJoCo 3.16.0's MJCF compiler, dynamics, collision
detection and constraint solver.

This is the starting skeleton. Every entry point below raises NotImplementedError. The full contract
(model and data fields, units, conventions, the supported MJCF subset) is in /app/README.txt and the
task instructions. You may split the implementation over any number of modules inside this package.
"""


class MJCFError(Exception):
    """Raised for invalid or unsupported models."""


def load_model(path):
    """Parse and compile the MJCF file at `path`; return a Model.

    The Model exposes the compiled fields listed in the instructions (nq, nv, body_pos, ...), named
    and shaped as in MuJoCo's mjModel, plus whatever internal state your engine needs.
    """
    raise NotImplementedError("load_model")


class Data:
    """Simulation state and outputs for one Model, named and shaped as in MuJoCo's mjData.

    Data(m) starts at qpos = m.qpos0 with every other input (qvel, act, ctrl, qfrc_applied,
    xfrc_applied, qacc) zero and time 0. Inputs are NumPy float arrays that callers fill in place.
    """

    def __init__(self, m):
        raise NotImplementedError("Data")


def forward(m, d):
    """Forward dynamics at the current state: kinematics, collision detection, the constraint solve,
    qacc and all sensors."""
    raise NotImplementedError("forward")


def inverse(m, d):
    """Inverse dynamics: qfrc_inverse from the current qpos, qvel and the given d.qacc."""
    raise NotImplementedError("inverse")


def step(m, d):
    """Advance the state by one timestep with the model's integrator (Euler, RK4, implicit or
    implicitfast)."""
    raise NotImplementedError("step")


def mass_matrix(m, d):
    """Return the dense (nv, nv) joint-space inertia matrix computed by the last forward/inverse call."""
    raise NotImplementedError("mass_matrix")
