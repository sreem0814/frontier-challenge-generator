mjlite reference card
=====================

This card lists exactly what the graded models use and what the harness reads. Semantics are MuJoCo 3.16.0's;
docs/mujoco-3.16.0/ holds the upstream documentation (XMLreference.rst is the MJCF reference, computation.rst
the equations, the constraint model, the constraint solver and collision detection, fluid.rst the fluid forces,
mjmodel.h and mjdata.h the field definitions).

1. MJCF subset
--------------
Every graded model is one self-contained XML file (no includes, assets, meshes, height fields, flexes or
plugins). Elements and attributes not listed here do not occur, except decorative ones (rgba, group, site
size where no touch sensor uses it), which must be accepted. Angles follow <compiler angle>; the default is
degrees.

<compiler>   angle (degree|radian), eulerseq (three of xyzXYZ), inertiafromgeom (false|true|auto),
             boundmass, boundinertia
<option>     timestep, gravity, integrator (Euler|RK4|implicit|implicitfast), solver (Newton|CG),
             tolerance (always 0), iterations, ls_iterations, cone (pyramidal|elliptic), impratio,
             density, viscosity, wind
  <flag>     each optional, value "disable": contact, constraint, equality, frictionloss, limit,
             filterparent, gravity, spring, damper, actuation, clampctrl, eulerdamp
<default>    nested, named with class; may hold joint (damping, armature, stiffness, axis, type,
             frictionloss, solreflimit), geom (type, size, density, friction, solref, condim), site (size)
             and motor (gear, ctrlrange). The top-level default is class "main".
<worldbody>  geom (static: planes, also sphere/capsule/box/cylinder), site, body, frame
<frame>      pos, orientation, childclass; contains bodies and frames
<body>       name, pos, orientation, childclass, gravcomp; contains joint, freejoint, geom, site, inertial,
             body, frame
<joint>      name, class, type (hinge|slide|ball|free), pos, axis, ref, springref, stiffness (1 or 3 values),
             damping (1 or 3 values), armature, range, limited, margin, solreflimit, solimplimit,
             frictionloss, solreffriction
<freejoint>  name (no joint defaults apply)
<inertial>   pos, mass, and either diaginertia with an optional orientation, or fullinertia
<geom>       name, class, type (plane|sphere|capsule|cylinder|box|ellipsoid), size, fromto, pos,
             orientation, mass, density, shellinertia, contype, conaffinity, condim (1|3|4|6), priority,
             friction, solmix, solref, solimp, margin, gap, fluidshape (none|ellipsoid), fluidcoef
<site>       name, class, pos, orientation, type and size (the volume of a touch sensor)
<contact>    pair (geom1, geom2, condim, friction (5 values), solref, solimp, margin); exclude (body1, body2)
<equality>   connect (body1 [body2] anchor, or site1 site2), weld (body1 [body2], anchor, relpose,
             torquescale), joint (joint1 [joint2], polycoef), tendon (tendon1 [tendon2], polycoef);
             all with name, solref, solimp, active
<tendon>     fixed: name, stiffness, damping, springlength (1 or 2 values), range, limited, margin,
             solreflimit, frictionloss; children joint (joint, coef)
             spatial: the same attributes; children site (site), pulley (divisor) and wrapping geom
             (geom = a sphere or cylinder, optional sidesite)
<actuator>   motor, position (kp, kv, timeconst), velocity (kv), intvelocity (kp, actrange), damper (kv),
             cylinder (timeconst, area, bias), muscle (lengthrange always given; force, scale, timeconst,
             range, lmin, lmax, vmax, fpmax, fvmax, tausmooth), general (dyntype none|integrator|filter|
             filterexact, dynprm, gaintype fixed|affine, gainprm, biastype none|affine, biasprm, actrange,
             actearly). All: name, gear, ctrlrange, forcerange; motor may also take class.
             Transmissions: joint (hinge or slide: one gear value; ball: 3; free: 6), tendon, and site
             (6-value gear, optional refsite).
<sensor>     jointpos jointvel jointactuatorfrc (joint); ballquat ballangvel (joint, ball);
             jointlimitpos jointlimitvel jointlimitfrc (joint); tendonpos tendonvel tendonactuatorfrc
             tendonlimitpos tendonlimitvel tendonlimitfrc (tendon); actuatorpos actuatorvel actuatorfrc
             (actuator); framepos framequat framexaxis frameyaxis framezaxis framelinvel frameangvel
             (objtype body|xbody|site|geom, objname, optional reftype xbody|site|geom with refname);
             framelinacc frameangacc (objtype, objname); subtreecom subtreelinvel subtreeangmom (body);
             touch velocimeter gyro accelerometer force torque (site); e_potential e_kinetic.
             Optional on any sensor: name, cutoff, noise (noise has no effect on sensordata).
orientation  one of quat, axisangle, euler, xyaxes, zaxis.

Collision pairs. Ellipsoids never collide (contype = conaffinity = 0). Cylinders use contype 2 and
conaffinity 0; planes and spheres use conaffinity 3; everything else uses the defaults unless a geom sets
contype = conaffinity = 0. So every contact comes from one of MuJoCo's analytic pair functions:
plane-sphere, plane-capsule, plane-box, plane-cylinder, sphere-sphere, sphere-capsule, sphere-cylinder,
sphere-box, capsule-capsule, capsule-box and box-box. Explicit <pair> elements use only these combinations.

Solver settings. Whenever constraints are enabled the model sets tolerance="0", so MuJoCo ran its solver to
full convergence and the expected values are the unique optimum of the constraint problem (the hidden set
keeps only states where Newton and CG agree to a small fraction of the tolerance below). Any solver that
reaches the same optimum passes; you do not need MuJoCo's iteration history.

2. Model fields read by the harness
-----------------------------------
Integers: nq nv nu na nbody njnt nsite ntendon ngeom neq.
Integer arrays: body_parentid (nbody), jnt_type (njnt; 0 free, 1 ball, 2 slide, 3 hinge), jnt_bodyid,
jnt_qposadr, jnt_dofadr (njnt), dof_bodyid, dof_parentid (nv; -1 for none), geom_type (ngeom; 0 plane,
2 sphere, 3 capsule, 4 ellipsoid, 5 cylinder, 6 box), geom_bodyid (ngeom).
Float arrays: body_pos (nbody,3), body_quat (nbody,4), body_ipos (nbody,3), body_iquat (nbody,4), body_mass
(nbody), body_inertia (nbody,3), jnt_pos (njnt,3), jnt_axis (njnt,3), geom_pos (ngeom,3), geom_quat
(ngeom,4), geom_size (ngeom,3), jnt_stiffness (njnt), qpos0 (nq), qpos_spring (nq), dof_armature (nv),
dof_damping (nv), body_invweight0 (nbody,2), dof_invweight0 (nv), tendon_invweight0 (ntendon),
actuator_acc0 (nu).
Body 0 is the world body. Ids follow MuJoCo's ordering (bodies depth-first in document order; joints, dofs,
geoms, sites, equalities and sensors in tree/document order).

3. Data fields
--------------
Inputs, NumPy float arrays the harness fills in place: qpos (nq), qvel (nv), act (na), ctrl (nu),
qfrc_applied (nv), xfrc_applied (nbody,6: world-frame force then torque, applied at the body's CoM), and
qacc (nv) as the input of inverse().
Read after forward(): xpos (nbody,3), xmat (nbody,9), xipos (nbody,3), subtree_com (nbody,3), site_xpos
(nsite,3), site_xmat (nsite,9), ten_length, ten_velocity (ntendon), actuator_length, actuator_velocity,
actuator_force (nu), qfrc_bias, qfrc_passive, qfrc_actuator, qfrc_constraint, qacc (nv), act_dot (na),
sensordata (nsensordata), mass_matrix(m, d) as a dense (nv,nv) array, and the constraint bookkeeping:
  ne, nf, nl, nefc   ints: equality rows, friction-loss rows, limit rows, all constraint rows
  ncon               int: number of contacts (including contacts in the margin-gap band)
  contact.<field>    array-likes indexed by contact, MuJoCo layout: geom (ncon,2) ordered geom ids,
                     dim (ncon), dist (ncon), pos (ncon,3), frame (ncon,9: normal first, then the two
                     tangent axes), friction (ncon,5), solref (ncon,2), solimp (ncon,5), includemargin (ncon)
Read after inverse(): qfrc_inverse (nv).
Read after step() called N times: qpos, qvel, act.
Arrays are read with numpy.asarray(x, dtype=float).ravel(), so (n,3) and flat layouts are both fine;
rotation matrices are row-major (xmat[i].reshape(3,3) maps local to world). For contact fields the harness
takes the first k*ncon elements, so preallocated larger arrays are fine.

4. Harness sequence, per model (tools/run_model.py is the exact code)
---------------------------------------------------------------------
m = mjlite.load_model(path); then for each state: (a) d = mjlite.Data(m), set inputs, mjlite.forward(m, d),
read; (b) a fresh Data, set inputs and d.qacc, mjlite.inverse(m, d), read; (c) a fresh Data, set inputs,
mjlite.step(m, d) N times (3 <= N <= 10, the same N for all states of a model), read. Each phase is isolated:
an exception loses only that phase's cases. A fresh Data has no warm start: the result must not depend on
one.

5. Case buckets and weights
---------------------------
Per model: tree 1 (all integer fields), frames 1 (body_pos, body_quat, jnt_pos, jnt_axis, geom_pos,
geom_quat, geom_size), inertia 1 (body_mass, body_ipos, inertia tensor), dofs 1 (qpos0, qpos_spring,
dof_armature, dof_damping, jnt_stiffness), invweight 3 (body_invweight0, dof_invweight0, tendon_invweight0,
actuator_acc0).
Per state: kin_body 1 (xpos, xmat), kin_com 1 (xipos, subtree_com), kin_site 1 (site_xpos, site_xmat; models
with sites), mass 1, bias 1 (qfrc_bias), transmission 4 (ten_length, ten_velocity, actuator_length,
actuator_velocity; models with tendons or actuators), passive 4 (qfrc_passive), actuation 4 (actuator_force,
qfrc_actuator, act_dot; models with actuators), contacts 16 (the contact list; models with contacts
enabled), efc_rows 5 (ne, nf, nl, nefc; models with constraints enabled), constraint 12 (qfrc_constraint;
models with constraints enabled), accel 12 (qacc), inverse 10 (qfrc_inverse), step 13 (qpos, qvel, act after
N steps), sensor_pos 2, sensor_vel 2, sensor_acc 4 (sensordata entries of sensors computed at the position,
velocity and acceleration stage; models with such sensors).
A float array passes when it has the expected length and every element satisfies
|got - exp| <= 1e-6 |exp| + 1e-8 max|exp over the array| + 1e-10. Quaternions (body_quat, geom_quat, the
quaternion parts of qpos0/qpos_spring/qpos, ballquat and framequat readings) may have either sign. The
inertia case compares mass, body_ipos and the full inertia tensor R(body_iquat) diag(body_inertia) R^T, so
the order and sign of principal axes are free. The contact case needs the same ncon and a one-to-one match
of contacts (in any order) with the same ordered geom pair and dim whose dist, pos, frame, friction,
solref, solimp and includemargin pass the tolerance (the max runs over that field of all contacts).
efc_rows compares the four integers exactly.

6. Model families
-----------------
The generator draws each model from one of six families (approximate shares of the hidden set):
smooth 5 % (contacts and constraints disabled), joint 12 % (limits, friction loss, equality constraints;
no contacts), contact_light 25 % (planes, spheres, capsules, cylinders), contact_full 30 % (all analytic
pairs, boxes included), actuated 16 % (muscles, site/ball/free transmissions, wrapping tendons; contacts in
about 60 % of them) and fluid 12 % (fluid forces; contacts in about 60 % of them). Integrators: Euler 30 %, RK4 15 %, implicit 25 %,
implicitfast 30 %. The expected file of each example names its family.
