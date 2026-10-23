# Provenance

## Source

MuJoCo, the physics engine maintained by Google DeepMind: https://github.com/google-deepmind/mujoco, release
3.16.0 (tag `3.16.0`, commit a892750516336d8358949f4518fcc4fbbd85beae, October 2026), Apache-2.0. The
behavior being ported is that release's MJCF compiler (`src/user`, `src/xml`) and simulation pipeline
(`src/engine`: `engine_core_smooth.c`, `engine_passive.c`, `engine_forward.c`, `engine_inverse.c`,
`engine_sensor.c`, `engine_collision_driver.c`, `engine_collision_primitive.c`, `engine_collision_box.c`,
`engine_core_constraint.c`, `engine_solver.c`, `engine_setconst.c`, `engine_derivative.c`). The expected outputs come from the official `mujoco==3.16.0` wheel on PyPI.

## Extraction

The image ships no MuJoCo code. `/app` holds an empty package skeleton (`mjlite`), the upstream
documentation of the same release (`doc/XMLreference.rst`, `doc/overview.rst`, `doc/modeling.rst`,
`doc/computation/index.rst`, `doc/computation/fluid.rst`, `doc/programming/simulation.rst`, `include/mujoco/mjmodel.h` and `mjdata.h`,
plus the Apache-2.0 license; the only edit is a wording change that spells out every short reference to the
constraint solver as "the constraint solver"),
24 random example models with MuJoCo's outputs, 6 hand-written examples, and a self-check that scores
examples the same way the grader scores the hidden set.

The scope is cut down from the full engine to keep it gradable to six digits: contacts come only from
MuJoCo's analytic primitive pair functions (ellipsoids never collide and cylinders meet only planes and
spheres, so the general convex GJK/EPA path is never used), and meshes, height fields, flexes, plugins and
the PGS solver are left out. What remains is the MJCF subset in `/app/README.txt`: the compiler, smooth
dynamics, fluid forces, collision detection, the soft constraint model with Newton and CG, four integrators,
tendons with wrapping, eight actuator kinds and 37 sensor types.

A model generator (written for this task, not shipped) draws random models from six families over that
subset. MuJoCo 3.16.0 compiled each model and computed, for four states (random, or a short simulation into
contact followed by a velocity kick), the kinematics, the inertia matrix, all force components, the contact
list, constraint forces, accelerations, inverse dynamics, sensor readings and a 3 to 10 step rollout. Those
outputs were frozen as the hidden set (192 models) and the examples (other seeds). States were kept only
when the constraint optimum was unique and converged (Newton and CG, run with tolerance 0, agree to a
thousandth of the tolerance) and stable (perturbing the state by 1e-7 changes no contact and moves no output
discontinuously); models MuJoCo rejected, badly conditioned ones and deep overlaps were skipped.

The reference solution (`solution/mjlite`, about 1,900 lines) is our port of the same upstream functions,
written from the 3.16.0 sources. On 300 further random models it passes every case with the largest error
at 1e-4 of the tolerance, and an alternative implementation (mass matrix from body Jacobians, Cholesky
solves, a different principal-axis convention) also passes every case, so the tolerance leaves room for
valid differences in summation order.

## Why it is real work

Engineers re-implement a simulator's model compiler and dynamics outside the original code base all
the time in robotics and graphics: differentiable or GPU ports (MuJoCo's own MJX and MuJoCo Warp re-implement this
pipeline in JAX and Warp), digital twins on embedded targets, and teaching code. The engineer has to
reproduce the compiler's defaults and inertia rules exactly, keep MuJoCo's coordinate conventions for free
and ball joints, implement the composite-rigid-body and recursive Newton-Euler algorithms, and match
integrator, actuator and sensor semantics to the last detail, checking each stage against the reference
engine's numbers as they go.
