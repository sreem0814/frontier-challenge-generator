# Port MuJoCo's MJCF compiler, dynamics and constraint pipeline to Python

We need a pure Python/NumPy re-implementation of MuJoCo 3.16.0's simulation pipeline for rigid
multibody models: the MJCF parser and compiler (defaults, frames, orientations, inertia from geoms, the
constants MuJoCo derives at compile time), forward kinematics, the joint-space inertia matrix, bias,
passive, fluid and actuator forces, collision detection between primitive geoms, the soft constraint model
(contacts, joint and tendon limits, friction loss, equality constraints) with its convex solver, forward
and inverse dynamics, the Euler, RK4, implicit and implicitfast integrators, tendons with wrapping, and
sensors. The package must reproduce MuJoCo's numbers, to about six significant digits, on random models it
has never seen. MuJoCo itself is not installed and there is no network.

You start from an empty package skeleton at `/app/mjlite`. Everything else you need is in `/app`.

## Workspace

```
/app/mjlite/__init__.py        the package you write (skeleton: every entry point raises NotImplementedError)
/app/README.txt                reference card: the MJCF subset, the fields the harness reads, the case buckets
/app/docs/mujoco-3.16.0/       upstream documentation at the 3.16.0 release:
    XMLreference.rst           MJCF elements, attributes and defaults
    computation.rst            equations of motion, actuation, passive forces, integrators, the
                               constraint model, the constraint solver and collision detection
    fluid.rst                  the inertia-box and ellipsoid fluid models
    overview.rst, modeling.rst kinematic tree, frames, defaults, inertia, contact parameters, muscles
    simulation.rst             the simulation pipeline and its stages
    mjmodel.h, mjdata.h        definitions of every mjModel / mjData field
/app/examples/                 24 random models drawn from the same generator as the hidden set:
    models/NNNN.xml            the MJCF file
    states/NNNN.json           the input states and the step count N
    expected/NNNN.json         MuJoCo 3.16.0's outputs for those states (and the model's family)
/app/examples/basic/           6 small hand-written models (pendulum, cart double pendulum, free box,
                               ball chain, box and ball on a floor, a limited chain with a joint
                               coupling) in the same layout, for getting started
/app/tools/selfcheck.py        scores your package on the examples exactly as the hidden set is scored
/app/tools/run_model.py        the harness that drives one model through your package (the grader runs this file)
/app/tools/cases.py            the case definitions, weights and tolerance check (the grader's copy is identical)
```

`/app` is a git repository with the skeleton committed; use it as you like.

## What to deliver

A package importable as `mjlite` from `/app/mjlite`, written in Python using only the standard library and
NumPy 1.24 (Debian's `python3` 3.11). Split it into as many modules as you want, but keep everything inside
`/app/mjlite`: that directory is the only thing the grader copies. The harness uses exactly this interface:

- `mjlite.load_model(path)` parses and compiles the MJCF file at `path` and returns a model object.
- `mjlite.Data(m)` creates the state for that model: `qpos = m.qpos0`, every other input zero, time 0.
- `mjlite.forward(m, d)` computes everything MuJoCo's `mj_forward` computes for the listed outputs:
  kinematics, inertia, tendon and actuator lengths and velocities, passive (including fluid), bias and
  actuator forces, contacts, constraint forces, `qacc`, `act_dot` and all sensors.
- `mjlite.inverse(m, d)` computes `d.qfrc_inverse` from `d.qpos`, `d.qvel` and the given `d.qacc`, as
  `mj_inverse` does (constraint forces included, from the soft constraint model at that `qacc`).
- `mjlite.step(m, d)` advances one timestep like `mj_step` with the model's integrator (`Euler`, `RK4`,
  `implicit` or `implicitfast`), updating `qpos`, `qvel`, `act` and `time`.
- `mjlite.mass_matrix(m, d)` returns the dense `(nv, nv)` inertia matrix of the last forward or inverse call.

Model and data fields carry MuJoCo's names, units and layouts; `/app/README.txt` lists every field the
harness reads, with shapes. From the model: the sizes `nq nv nu na nbody njnt nsite ntendon ngeom neq`; the
tree (`body_parentid`, `jnt_type`, `jnt_bodyid`, `jnt_qposadr`, `jnt_dofadr`, `dof_bodyid`, `dof_parentid`,
`geom_type`, `geom_bodyid`); frames (`body_pos`, `body_quat`, `jnt_pos`, `jnt_axis`, `geom_pos`,
`geom_quat`, `geom_size`); inertia (`body_mass`, `body_ipos`, `body_iquat`, `body_inertia`); `qpos0`,
`qpos_spring`, `dof_armature`, `dof_damping`, `jnt_stiffness`; and the compile-time constants
`body_invweight0`, `dof_invweight0`, `tendon_invweight0` and `actuator_acc0`. From the data after
`forward`: `xpos xmat xipos subtree_com site_xpos site_xmat ten_length ten_velocity actuator_length
actuator_velocity actuator_force qfrc_bias qfrc_passive qfrc_actuator qfrc_constraint qacc act_dot
sensordata`, the row counts `ne nf nl nefc`, and the contact list: `ncon` and `d.contact.geom`, `dim`,
`dist`, `pos`, `frame`, `friction`, `solref`, `solimp`, `includemargin` (MuJoCo's layouts, one row per
contact). Then `qfrc_inverse` after `inverse`, and `qpos qvel act` after N calls to `step`.

Inputs are NumPy float arrays the harness fills in place (`d.qpos[:] = ...`): `qpos`, `qvel`, `act`,
`ctrl`, `qfrc_applied`, `xfrc_applied` (shape `(nbody, 6)`, world-frame force then torque at the body's
center of mass) and `qacc` for `inverse`. Outputs may be any array-like that `numpy.asarray(x,
dtype=float).ravel()` turns into the right number of elements.

The MJCF subset is broad, but closed; `/app/README.txt` lists every element and attribute that occurs. In
short: compiler angle units, Euler sequences, `inertiafromgeom`, `boundmass`, `boundinertia`; options for
timestep, gravity, integrator, solver, cone, impratio, fluid density, viscosity and wind, and disable flags
(contact, constraint, equality, frictionloss, limit, filterparent, gravity, spring, damper, actuation,
clampctrl, eulerdamp); nested default classes and `childclass`; `frame` elements; all five orientation
forms; hinge, slide, ball and free joints with limits, margins, friction loss and solver parameters;
plane, sphere, capsule, cylinder, box and ellipsoid geoms with `fromto`, mass or density, `shellinertia`,
contact filtering (`contype`, `conaffinity`, parent filtering, `exclude`), explicit `pair`s, `condim`
1/3/4/6, `priority`, `solmix`, `friction`, `solref`, `solimp`, `margin`, `gap`, and fluid shape
parameters; explicit inertials; sites; fixed and spatial tendons (pulleys, sphere and cylinder wrapping
with side sites, limits, friction loss); connect, weld, joint and tendon equality constraints; motor,
position, velocity, intvelocity, damper, cylinder, muscle and general actuators on joint, tendon, site
(with refsite), ball and free transmissions; and 37 sensor types including touch and the limit sensors.

Collisions are restricted to MuJoCo's analytic pair functions: ellipsoids never collide and cylinders only
meet planes and spheres (see the card for the contype/conaffinity convention), so every contact comes from
plane-sphere, plane-capsule, plane-box, plane-cylinder, sphere-sphere, sphere-capsule, sphere-cylinder,
sphere-box, capsule-capsule, capsule-box or box-box. Models with constraints set `tolerance="0"`, so the
expected values are the converged, unique optimum of MuJoCo's constraint problem; any solver that converges
to it passes, and the result must not depend on a warm start (each state starts from a fresh `Data`).

Where the documentation leaves a detail open, MuJoCo 3.16.0's behavior on the examples settles it. The
expected outputs are MuJoCo's own: every convention matters, including quaternion order `(w, x, y, z)`,
free-joint velocities (linear in the world frame, angular in the body frame), the order of geoms in a
contact and the direction of its normal, the contact frame's tangent axes, how contact parameters of two
geoms are mixed, how `solref` and `solimp` turn into impedance and reference acceleration, the diagonal
approximation behind the regularizer, the pyramidal and elliptic cone formulations, and how the implicit
integrators treat damping and actuator velocity terms.

## Building and checking your work

There is no build step: the grader imports your source. Run the self-check whenever you change something:

```
python3 /app/tools/selfcheck.py            # all 24 examples, prints bucket counts and an estimated score
python3 /app/tools/selfcheck.py -v -j 8    # also prints the first error of each failing model
python3 /app/tools/selfcheck.py --only 0007
python3 /app/tools/selfcheck.py --examples /app/examples/basic
```

It copies `/app/mjlite` to a scratch directory, runs every example in its own `python3 -I` process through
`tools/run_model.py` with the grader's 240-second limit per model, and compares the outputs with
`tools/cases.py`, the same code the grader uses. It also checks the hard gates below. For debugging, load an
example yourself and compare single arrays against `expected/NNNN.json`; the expected file stores every
graded array per state (contacts as `con_*` arrays), plus `sensor_idx` (which `sensordata` entries belong to
which stage).

The examples are a small sample. The hidden set has 192 models from the same random generator with
different seeds and the same family mix, so a feature you see once in the examples shows up in dozens of
hidden models.

## Scoring

The grader copies `/app/mjlite`, then runs each of the 192 hidden models through `tools/run_model.py` as an
unprivileged user, in its own process, with 240 seconds of wall-clock time per model (load plus four
states). A model that crashes, hangs or times out keeps whatever cases it finished; the rest fail.

Each model contributes five compile cases and, for each of its four states, up to 17 state cases. Every
case falls in one of 22 buckets with a fixed weight:

| bucket | weight | compared |
|---|---|---|
| tree | 1 | all integer model fields |
| frames | 1 | body_pos, body_quat, jnt_pos, jnt_axis, geom_pos, geom_quat, geom_size |
| inertia | 1 | body_mass, body_ipos, full inertia tensor |
| dofs | 1 | qpos0, qpos_spring, dof_armature, dof_damping, jnt_stiffness |
| invweight | 3 | body_invweight0, dof_invweight0, tendon_invweight0, actuator_acc0 |
| kin_body | 1 | xpos, xmat |
| kin_com | 1 | xipos, subtree_com |
| kin_site | 1 | site_xpos, site_xmat |
| mass | 1 | mass_matrix |
| bias | 1 | qfrc_bias |
| transmission | 4 | ten_length, ten_velocity, actuator_length, actuator_velocity |
| passive | 4 | qfrc_passive |
| actuation | 4 | actuator_force, qfrc_actuator, act_dot |
| contacts | 16 | ncon and the contact list (models with contacts enabled) |
| efc_rows | 5 | ne, nf, nl, nefc (models with constraints enabled) |
| constraint | 12 | qfrc_constraint (models with constraints enabled) |
| accel | 12 | qacc |
| inverse | 10 | qfrc_inverse |
| step | 13 | qpos, qvel, act after N steps |
| sensor_pos, sensor_vel, sensor_acc | 2, 2, 4 | sensordata entries of sensors evaluated at that stage |

A float array passes when it has the expected number of elements and each element satisfies
`|got - exp| <= 1e-6 * |exp| + 1e-8 * max|exp| + 1e-10`, where the maximum runs over that array.
Quaternions may come out with either sign. The inertia case compares the tensor
`R(body_iquat) diag(body_inertia) R^T`, so the order and sign of principal axes are free. The contact case
needs the same `ncon` and a one-to-one match, in any order, of contacts with the same ordered geom pair and
`dim` whose `dist`, `pos`, `frame`, `friction`, `solref`, `solimp` and `includemargin` pass the tolerance
(the maximum runs over that field of all contacts). `efc_rows` compares four integers exactly. Buckets that
a model does not use contribute no cases.

The reward is

```
reward = sum_b w_b * passed_b / total_b  /  sum_b w_b
```

over the buckets of the hidden set, with fixed totals: a case that errors, times out or is missing counts as
failed. MuJoCo's own outputs define every expected value and the reference implementation passes every
case, so a complete port scores 1.0 and the untouched skeleton scores 0.

Hard gates. Any of these sets the reward to exactly 0, and `selfcheck.py` prints `gates: FAIL` with the
reason when one applies:

1. `/app/mjlite/__init__.py` must exist.
2. The package must be plain source: no symbolic links and no compiled or native files (`.so`, `.pyd`,
   `.dll`, `.dylib`, `.o`, `.a`) anywhere inside `/app/mjlite`.
3. The system Python must be unmodified. The grader runs
   `dpkg --verify python3.11-minimal libpython3.11-minimal libpython3.11-stdlib` and any changed or missing
   file fails the run (documentation, man pages and lintian files, which the image never installs, are
   ignored). Run the same command yourself if you are unsure.

## Time budget

You have 8 hours. The real remaining budget is in `/app/.timer`: run `cat /app/.timer/remaining_secs`
before any long debugging session or refactor, and expect `alert_30min` and then `alert_10min` to appear
there as time runs low. The container clock does not tell you how much budget is left; the timer does.

## Constraints

- No network, no `pip install`, no other Python packages. MuJoCo's C source and Python bindings are not
  available; the documentation in `/app/docs` and the examples are your references.
- The harness runs `python3 -I`, so `PYTHONPATH`, user site directories and edits to environment variables
  have no effect. Do not depend on files outside `/app/mjlite` at grading time.
- Keep each hidden model, with its four states, under 240 seconds on one core. Avoid per-call
  recompilation and deep Python loops over large arrays; a dense NumPy solver is fast enough at these sizes
  (at most 12 bodies, a few dozen constraint rows).
- Results must be deterministic: no randomness, no dependence on the time of day.

## Operating rules

Nobody will answer questions during the run, so make the calls yourself and keep going. The smooth
dynamics (compiler, kinematics, inertia matrix, bias forces) are the foundation but carry little weight on
their own; most of the score sits in what depends on the constraint pipeline: contacts, constraint forces,
accelerations, inverse dynamics and multi-step rollouts with every integrator. Work outward from a correct
foundation, use the model families in the expected files to see which subsystem a failure belongs to, and
compare single arrays against the expected outputs when a bucket stalls. After each change run the
self-check, keep what raises the score and back out what lowers it; commit to git whenever the score
improves so you always have a good state to return to. A partial port earns partial credit, but only if it
imports and runs, so never leave the package broken. Check `/app/.timer` before starting anything big and
stop starting new features when `alert_30min` appears. The visible examples are for calibration only; the
hidden models are new random models, so implement the general rule rather than patching single examples.
