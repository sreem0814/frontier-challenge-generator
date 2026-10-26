"""MJCF parsing and compilation into a Model.

Handles the subset of MJCF the package supports: compiler and option settings, nested default classes,
childclass, frames, bodies with all orientation alternatives, inertials, geoms (mass from primitives),
sites, joints, fixed tendons and the motor/position/velocity/general actuators.
"""
import math
import xml.etree.ElementTree as ET

import numpy as np

from . import spatial as sp
from .model import Model, JNT_FREE, JNT_BALL, JNT_SLIDE, JNT_HINGE, Option

JTYPES = {"free": JNT_FREE, "ball": JNT_BALL, "slide": JNT_SLIDE, "hinge": JNT_HINGE}
GEOM_TYPES = ("plane", "hfield", "sphere", "capsule", "ellipsoid", "cylinder", "box", "mesh")
UNDEF = None
NAN = float("nan")


class MJCFError(Exception):
    pass


# ---------------------------------------------------------------- attribute schema
# numeric arrays: (length, default). Partial values overwrite the leading components only.
NUM = {
    "joint": {"pos": (3, [0, 0, 0]), "axis": (3, [0, 0, 1]), "ref": (1, [0]), "springref": (1, [0]),
              "stiffness": (3, [0, 0, 0]), "damping": (3, [0, 0, 0]), "armature": (1, [0]),
              "range": (2, [0, 0]), "frictionloss": (1, [0]), "margin": (1, [0]), "group": (1, [0])},
    "geom": {"size": (3, [0, 0, 0]), "pos": (3, [0, 0, 0]), "quat": (4, [1, 0, 0, 0]),
             "fromto": (6, None), "mass": (1, None), "density": (1, [1000]), "group": (1, [0]),
             "axisangle": (4, None), "euler": (3, None), "xyaxes": (6, None), "zaxis": (3, None)},
    "site": {"pos": (3, [0, 0, 0]), "quat": (4, [1, 0, 0, 0]), "size": (3, [0.005, 0.005, 0.005]),
             "axisangle": (4, None), "euler": (3, None), "xyaxes": (6, None), "zaxis": (3, None),
             "fromto": (6, None)},
    "actuator": {"gear": (6, [1, 0, 0, 0, 0, 0]), "ctrlrange": (2, [0, 0]), "forcerange": (2, [0, 0]),
                 "actrange": (2, [0, 0]), "dynprm": (10, [1] + [0] * 9), "gainprm": (10, [1] + [0] * 9),
                 "biasprm": (10, [0] * 10), "kp": (1, None), "kv": (1, None), "timeconst": (1, None)},
}
STR = {
    "joint": {"type": "hinge", "limited": "auto"},
    "geom": {"type": "sphere", "shellinertia": "false"},
    "site": {},
    "actuator": {"ctrllimited": "auto", "forcelimited": "auto", "actlimited": "auto", "dyntype": "none",
                 "gaintype": "fixed", "biastype": "none", "actearly": "false"},
}
ACTUATOR_TAGS = ("general", "motor", "position", "velocity")
ORIENT_KEYS = ("quat", "axisangle", "euler", "xyaxes", "zaxis")


def parse_nums(text):
    try:
        return [float(x) for x in text.split()]
    except ValueError:
        raise MJCFError(f"bad number list {text!r}")


class Spec:
    """Attribute values for one element kind: numeric arrays plus strings, overlaid level by level."""

    def __init__(self, kind, base=None):
        self.kind = kind
        if base is None:
            self.num = {k: (list(v[1]) if v[1] is not None else None) for k, v in NUM[kind].items()}
            self.str = dict(STR[kind])
            self.given = set()
        else:
            self.num = {k: (list(v) if v is not None else None) for k, v in base.num.items()}
            self.str = dict(base.str)
            self.given = set(base.given)

    def overlay(self, el):
        for key, text in el.attrib.items():
            if key in NUM[self.kind]:
                vals = parse_nums(text)
                n, default = NUM[self.kind][key]
                cur = self.num.get(key)
                if cur is None:
                    cur = list(default) if default is not None else [0.0] * n
                for i, v in enumerate(vals[:n]):
                    cur[i] = v
                self.num[key] = cur
                self.given.add(key)
                if key in ORIENT_KEYS:
                    self.given.add("orient:" + key)
            else:
                self.str[key] = text
                self.given.add(key)
        return self

    def copy(self):
        return Spec(self.kind, self)


class DefaultClass:
    def __init__(self, name, parent=None):
        self.name = name
        self.specs = {k: (parent.specs[k].copy() if parent else Spec(k)) for k in NUM}


# ---------------------------------------------------------------- orientation helpers

class Ctx:
    def __init__(self):
        self.degree = True
        self.eulerseq = "xyz"


def resolve_orientation(attrs, ctx, default_quat=(1, 0, 0, 0)):
    """attrs: dict of attribute name -> list of floats (only the ones given). Returns a unit quaternion."""
    if "quat" in attrs:
        return sp.normalize4(attrs["quat"])
    if "axisangle" in attrs:
        a = list(attrs["axisangle"])
        ang = a[3] * math.pi / 180 if ctx.degree else a[3]
        axis, n = sp.normalize3(a[:3])
        if n < sp.EPS:
            raise MJCFError("axisangle too small")
        return sp.normalize4(sp.axis_angle2quat(axis, ang))
    if "xyaxes" in attrs:
        v = attrs["xyaxes"]
        x, n = sp.normalize3(v[:3])
        if n < sp.EPS:
            raise MJCFError("xaxis too small")
        y = np.asarray(v[3:6], float)
        y = y - x * float(x @ y)
        y, n = sp.normalize3(y)
        if n < sp.EPS:
            raise MJCFError("yaxis too small")
        z, n = sp.normalize3(np.cross(x, y))
        return sp.mat2quat(np.column_stack([x, y, z]))
    if "zaxis" in attrs:
        z, n = sp.normalize3(attrs["zaxis"])
        if n < sp.EPS:
            raise MJCFError("zaxis too small")
        return sp.z2quat(z)
    if "euler" in attrs:
        e = list(attrs["euler"])
        if ctx.degree:
            e = [x * math.pi / 180 for x in e]
        q = np.array([1.0, 0, 0, 0])
        for i in range(3):
            c = ctx.eulerseq[i]
            qr = np.array([math.cos(e[i] / 2), 0.0, 0.0, 0.0])
            qr["xyz".index(c.lower()) + 1] = math.sin(e[i] / 2)
            q = sp.quat_mul(q, qr) if c.islower() else sp.quat_mul(qr, q)
        return sp.normalize4(q)
    return sp.normalize4(default_quat)


def element_orientation(el, ctx):
    attrs = {}
    for k in ORIENT_KEYS:
        if k in el.attrib:
            attrs[k] = parse_nums(el.attrib[k])
    return resolve_orientation(attrs, ctx)


def spec_orientation(spec, ctx):
    attrs = {}
    for k in ORIENT_KEYS:
        if ("orient:" + k) in spec.given and spec.num.get(k) is not None:
            attrs[k] = spec.num[k]
    return resolve_orientation(attrs, ctx, spec.num["quat"])


def elem_pos(el):
    return np.array(parse_nums(el.attrib["pos"])[:3] + [0.0] * (3 - len(parse_nums(el.attrib["pos"])[:3]))) \
        if "pos" in el.attrib else np.zeros(3)


# ---------------------------------------------------------------- geom mass properties

def geom_volume(t, s, shell):
    pi = math.pi
    if t == "sphere":
        return 4 * pi * s[0] ** 2 if shell else 4 * pi * s[0] ** 3 / 3
    if t == "capsule":
        h, r = 2 * s[1], s[0]
        return 4 * pi * r * r + 2 * pi * r * h if shell else pi * (r * r * h + 4 * r ** 3 / 3)
    if t == "cylinder":
        h, r = 2 * s[1], s[0]
        return 2 * pi * r * r + 2 * pi * r * h if shell else pi * r * r * h
    if t == "ellipsoid":
        if shell:
            p = 1.6075
            tmp = (s[0] * s[1]) ** p + (s[1] * s[2]) ** p + (s[2] * s[0]) ** p
            return 4 * pi * (tmp / 3) ** (1 / p)
        return 4 * pi * s[0] * s[1] * s[2] / 3
    if t == "box":
        return 8 * (s[0] * s[1] + s[1] * s[2] + s[2] * s[0]) if shell else 8 * s[0] * s[1] * s[2]
    return 0.0


def geom_inertia(t, s, mass, shell):
    if t == "sphere":
        v = 2 * mass * s[0] ** 2 / (3 if shell else 5)
        return [v, v, v]
    if t == "capsule":
        hh, h, r = s[1], 2 * s[1], s[0]
        if not shell:
            ms = mass * 4 * r / (4 * r + 3 * h)
            mc = mass - ms
            ixy = mc * (3 * r * r + h * h) / 12
            iz = mc * r * r / 2
            si = 2 * ms * r * r / 5
            ixy += si + ms * h * (3 * r + 2 * h) / 8
            return [ixy, ixy, iz + si]
        As, Ac = 4 * math.pi * r * r, 2 * math.pi * r * h
        ms = mass * As / (As + Ac)
        mc = mass - ms
        ixy = mc * (6 * r * r + h * h) / 12
        iz = mc * r * r
        si = 2 * ms * r * r / 3
        hs_com = r / 2
        hs_pos = hh + hs_com
        ixy += si + ms * (hs_pos * hs_pos - hs_com * hs_com)
        return [ixy, ixy, iz + si]
    if t == "cylinder":
        hh, h, r = s[1], 2 * s[1], s[0]
        if not shell:
            ixy = mass * (3 * r * r + h * h) / 12
            return [ixy, ixy, mass * r * r / 2]
        Ad, Ac = math.pi * r * r, 2 * math.pi * r * h
        md = mass * Ad / (2 * Ad + Ac)
        mc = mass - 2 * md
        ixy = mc * (6 * r * r + h * h) / 12
        iz = mc * r * r
        idx = md * r * r / 4 + md * hh * hh
        idz = md * r * r / 2
        return [ixy + 2 * idx, ixy + 2 * idx, iz + 2 * idz]
    if t == "ellipsoid":
        s00, s11, s22 = s[0] ** 2, s[1] ** 2, s[2] ** 2
        if not shell:
            return [mass * (s11 + s22) / 5, mass * (s00 + s22) / 5, mass * (s00 + s11) / 5]
        eps = 1e-6
        Va = 4 * math.pi * s[0] * s[1] * s[2] / 3
        ae, be, ce = s[0] + eps, s[1] + eps, s[2] + eps
        Vb = 4 * math.pi * ae * be * ce / 3
        dens = mass / (Vb - Va)
        ma, mb = Va * dens, Vb * dens
        ia = [ma * (s11 + s22) / 5, ma * (s00 + s22) / 5, ma * (s00 + s11) / 5]
        ib = [mb * (be * be + ce * ce) / 5, mb * (ae * ae + ce * ce) / 5, mb * (ae * ae + be * be) / 5]
        return [ib[i] - ia[i] for i in range(3)]
    if t == "box":
        s00, s11, s22 = s[0] ** 2, s[1] ** 2, s[2] ** 2
        if not shell:
            return [mass * (s11 + s22) / 3, mass * (s00 + s22) / 3, mass * (s00 + s11) / 3]
        lx, ly, lz = 2 * s[0], 2 * s[1], 2 * s[2]
        A0, A1, A2 = lx * ly, ly * lz, lz * lx
        At = 2 * (A0 + A1 + A2)
        m0, m1, m2 = mass * A0 / At, mass * A1 / At, mass * A2 / At
        Ix0, Iy0, Iz0 = m0 * ly * ly / 12, m0 * lx * lx / 12, m0 * (lx * lx + ly * ly) / 12
        Ix1, Iy1, Iz1 = m1 * (ly * ly + lz * lz) / 12, m1 * lz * lz / 12, m1 * ly * ly / 12
        Ix2, Iy2, Iz2 = m2 * lz * lz / 12, m2 * (lx * lx + lz * lz) / 12, m2 * lx * lx / 12
        return [2 * (m0 * s22 + m2 * s11 + Ix0 + Ix1 + Ix2),
                2 * (m0 * s22 + m1 * s00 + Iy0 + Iy1 + Iy2),
                2 * (m1 * s00 + m2 * s11 + Iz0 + Iz1 + Iz2)]
    return [0.0, 0.0, 0.0]


def principal(full):
    """Symmetric 3x3 tensor -> (quat of principal frame, moments sorted in decreasing order)."""
    # alternative: ascending moments, Jacobi-free eigh, quaternion with w <= 0
    w, V = np.linalg.eigh(full)
    if np.linalg.det(V) < 0:
        V[:, 0] = -V[:, 0]
    q = sp.mat2quat(V)
    return -q if q[0] > 0 else q, [float(x) for x in w]


# ---------------------------------------------------------------- intermediate objects

class BodyRec:
    def __init__(self, bid, parent, name):
        self.id, self.parent, self.name = bid, parent, name
        self.pos, self.quat = np.zeros(3), np.array([1.0, 0, 0, 0])
        self.geoms, self.sites, self.joints = [], [], []
        self.inertial = None
        self.gravcomp = 0.0


class Compiler:
    def __init__(self, root):
        self.root = root
        self.ctx = Ctx()
        self.classes = {"main": DefaultClass("main")}
        self.opt = Option()
        self.ifg = "auto"
        self.boundmass = 0.0
        self.boundinertia = 0.0
        self.bodies = [BodyRec(0, -1, "world")]
        self.joint_names = {}
        self.tendons = []
        self.actuators = []

    # ------------------------------------------------ top level
    def run(self):
        if self.root.tag != "mujoco":
            raise MJCFError("root element must be <mujoco>")
        for el in self.root:
            if el.tag == "compiler":
                self.read_compiler(el)
        for el in self.root:
            if el.tag == "option":
                self.read_option(el)
            elif el.tag == "default":
                self.read_default(el, None)
        for el in self.root:
            if el.tag == "worldbody":
                self.read_children(el, self.bodies[0], "main", None)
        self.index_objects()
        for el in self.root:
            if el.tag == "tendon":
                self.read_tendons(el)
        for el in self.root:
            if el.tag == "actuator":
                self.read_actuators(el)
        for el in self.root:
            if el.tag == "sensor":
                self.read_sensors(el)
        return self.build()

    def index_objects(self):
        """Global ids of sites and geoms (body-major order) and name lookups."""
        self.site_list, self.geom_list = [], []
        for b in self.bodies:
            for s in b.sites:
                self.site_list.append((b.id, s))
            for g in b.geoms:
                self.geom_list.append((b.id, g))
        self.site_names = {s["name"]: i for i, (_, s) in enumerate(self.site_list) if s["name"]}
        self.geom_names = {g["name"]: i for i, (_, g) in enumerate(self.geom_list) if g["name"]}
        self.body_names = {b.name: b.id for b in self.bodies if b.name}
        self.body_names["world"] = 0

    def read_compiler(self, el):
        a = el.attrib
        if "angle" in a:
            if a["angle"] not in ("degree", "radian"):
                raise MJCFError("bad angle")
            self.ctx.degree = a["angle"] == "degree"
        if "eulerseq" in a:
            seq = a["eulerseq"]
            if len(seq) != 3 or any(c not in "xyzXYZ" for c in seq):
                raise MJCFError("bad eulerseq")
            self.ctx.eulerseq = seq
        if "inertiafromgeom" in a:
            self.ifg = a["inertiafromgeom"]
        if "boundmass" in a:
            self.boundmass = float(a["boundmass"])
        if "boundinertia" in a:
            self.boundinertia = float(a["boundinertia"])

    def read_option(self, el):
        a = el.attrib
        if "timestep" in a:
            self.opt.timestep = float(a["timestep"])
        if "gravity" in a:
            self.opt.gravity = np.array(parse_nums(a["gravity"])[:3], float)
        if "integrator" in a:
            integ = a["integrator"]
            if integ not in ("Euler", "RK4"):
                raise MJCFError(f"unsupported integrator {integ}")
            self.opt.integrator = integ
        for f in el:
            if f.tag == "flag":
                for k, v in f.attrib.items():
                    if v == "disable":
                        self.opt.disabled.add(k)
                    elif v == "enable":
                        self.opt.disabled.discard(k)

    def read_default(self, el, parent):
        name = el.attrib.get("class", "main")
        if parent is None:
            dc = self.classes["main"]
        else:
            dc = DefaultClass(name, parent)
            self.classes[name] = dc
        for ch in el:
            if ch.tag in ("joint", "geom", "site"):
                dc.specs[ch.tag].overlay(ch)
            elif ch.tag in ACTUATOR_TAGS:
                self.overlay_actuator(dc.specs["actuator"], ch)
            elif ch.tag == "default":
                self.read_default(ch, dc)

    @staticmethod
    def overlay_actuator(spec, el):
        spec.overlay(el)

    def spec_for(self, kind, el, cls):
        name = el.attrib.get("class", cls)
        if name not in self.classes:
            raise MJCFError(f"unknown class {name}")
        s = self.classes[name].specs[kind].copy()
        # orientation given on the element replaces any orientation from defaults
        if any(k in el.attrib for k in ORIENT_KEYS):
            for k in ORIENT_KEYS:
                s.given.discard("orient:" + k)
            s.num["quat"] = [1.0, 0, 0, 0] if "quat" in NUM[kind] else None
        attrs = {k: v for k, v in el.attrib.items() if k != "class"}
        tmp = ET.Element(el.tag, attrs)
        return s.overlay(tmp)

    # ------------------------------------------------ kinematic tree
    def read_children(self, el, body, cls, frame):
        """frame: (pos, quat) accumulated from enclosing <frame> elements, or None."""
        for ch in el:
            if ch.tag == "body":
                self.read_body(ch, body, cls, frame)
            elif ch.tag == "frame":
                fcls = ch.attrib.get("childclass", cls)
                fp, fq = elem_pos(ch), element_orientation(ch, self.ctx)
                if frame is not None:
                    fp, fq = sp.frame_accum(frame[0], frame[1], fp, fq)
                self.read_children(ch, body, fcls, (fp, sp.normalize4(fq)))
            elif ch.tag == "geom":
                body.geoms.append(self.make_geom(ch, cls, frame))
            elif ch.tag == "site":
                body.sites.append(self.make_site(ch, cls, frame))
            elif ch.tag in ("joint", "freejoint"):
                if body.id == 0:
                    raise MJCFError("joints are not allowed in the world body")
                body.joints.append(self.make_joint(ch, cls, frame))
            elif ch.tag == "inertial":
                if body.id == 0:
                    continue
                body.inertial = self.make_inertial(ch, frame)
            # cameras, lights and other decorative elements are ignored

    def read_body(self, el, parent, cls, frame):
        b = BodyRec(len(self.bodies), parent.id, el.attrib.get("name", ""))
        self.bodies.append(b)
        b.pos = elem_pos(el)
        b.quat = element_orientation(el, self.ctx)
        if frame is not None:
            b.pos, b.quat = sp.frame_accum(frame[0], frame[1], b.pos, b.quat)
            b.quat = sp.normalize4(b.quat)
        b.gravcomp = float(el.attrib.get("gravcomp", 0))
        bcls = el.attrib.get("childclass", cls)
        if bcls not in self.classes:
            raise MJCFError(f"unknown class {bcls}")
        self.read_children(el, b, bcls, None)

    def make_joint(self, el, cls, frame):
        if el.tag == "freejoint":
            s = Spec("joint")
            s.str["type"] = "free"
        else:
            s = self.spec_for("joint", el, cls)
        t = s.str["type"]
        if t not in JTYPES:
            raise MJCFError(f"bad joint type {t}")
        j = {"name": el.attrib.get("name", ""), "type": JTYPES[t]}
        pos = np.array(s.num["pos"], float)
        axis = np.array(s.num["axis"], float)
        if t in ("free", "ball"):
            axis = np.array([0.0, 0, 1])
        elif frame is not None:
            axis = sp.rot_vec_quat(axis, frame[1])
        axis, n = sp.normalize3(axis)
        if n < sp.EPS:
            raise MJCFError("axis too small in joint")
        if t == "free":
            pos = np.zeros(3)
        elif frame is not None:
            pos = frame[0] + sp.rot_vec_quat(pos, frame[1])
        ref, springref = s.num["ref"][0], s.num["springref"][0]
        if t == "hinge" and self.ctx.degree:
            ref *= math.pi / 180
            springref *= math.pi / 180
        j.update(pos=pos, axis=axis, ref=ref, springref=springref,
                 stiffness=s.num["stiffness"][0], stiffpoly=list(s.num["stiffness"][1:3]),
                 damping=s.num["damping"][0], damppoly=list(s.num["damping"][1:3]),
                 armature=s.num["armature"][0])
        if j["name"]:
            self.joint_names[j["name"]] = j
        return j

    def make_geom(self, el, cls, frame):
        s = self.spec_for("geom", el, cls)
        t = s.str["type"]
        if t not in GEOM_TYPES or t in ("hfield", "mesh"):
            raise MJCFError(f"unsupported geom type {t}")
        size = list(s.num["size"])
        shell = s.str.get("shellinertia", "false") == "true"
        if s.num.get("fromto") is not None and "fromto" in s.given:
            if t not in ("capsule", "cylinder", "ellipsoid", "box"):
                raise MJCFError("fromto requires capsule, cylinder, box or ellipsoid")
            ft = s.num["fromto"]
            vec = np.array([ft[0] - ft[3], ft[1] - ft[4], ft[2] - ft[5]])
            half = float(np.linalg.norm(vec)) / 2
            if half < sp.EPS:
                raise MJCFError("fromto points too close")
            vdir = vec / (2 * half)
            size[1] = half
            if t in ("ellipsoid", "box"):
                size[2] = size[1]
                size[1] = size[0]
            pos = np.array([(ft[0] + ft[3]) / 2, (ft[1] + ft[4]) / 2, (ft[2] + ft[5]) / 2])
            quat = sp.z2quat(vdir)
        else:
            pos = np.array(s.num["pos"], float)
            quat = spec_orientation(s, self.ctx)
        if frame is not None:
            pos, quat = sp.frame_accum(frame[0], frame[1], pos, quat)
            quat = sp.normalize4(quat)
        vol = geom_volume(t, size, shell)
        mass_attr = s.num.get("mass") if "mass" in s.given else None
        mass, inertia = 0.0, [0.0, 0.0, 0.0]
        if mass_attr is not None:
            if mass_attr[0] == 0:
                mass = 0.0
            elif vol > sp.EPS:
                mass = mass_attr[0]
                inertia = geom_inertia(t, size, mass, shell)
        else:
            dens = s.num["density"][0]
            if dens != 0:
                mass = dens * vol
                inertia = geom_inertia(t, size, mass, shell)
        group = int(s.num["group"][0])
        return {"type": t, "pos": pos, "quat": quat, "mass": mass, "inertia": inertia, "group": group,
                "name": el.attrib.get("name", "")}

    def make_site(self, el, cls, frame):
        s = self.spec_for("site", el, cls)
        pos = np.array(s.num["pos"], float)
        quat = spec_orientation(s, self.ctx)
        if frame is not None:
            pos, quat = sp.frame_accum(frame[0], frame[1], pos, quat)
            quat = sp.normalize4(quat)
        return {"name": el.attrib.get("name", ""), "pos": pos, "quat": quat}

    def make_inertial(self, el, frame):
        a = el.attrib
        if "mass" not in a:
            raise MJCFError("inertial requires mass")
        mass = float(a["mass"])
        ipos = elem_pos(el)
        if "fullinertia" in a:
            if any(k in a for k in ORIENT_KEYS):
                raise MJCFError("fullinertia and inertial orientation cannot both be specified")
            f = parse_nums(a["fullinertia"])
            full = np.array([[f[0], f[3], f[4]], [f[3], f[1], f[5]], [f[4], f[5], f[2]]])
            iquat, inertia = principal(full)
        else:
            if "diaginertia" not in a:
                raise MJCFError("inertial requires diaginertia or fullinertia")
            inertia = parse_nums(a["diaginertia"])[:3]
            iquat = element_orientation(el, self.ctx)
        if frame is not None:
            ipos, iquat = sp.frame_accum(frame[0], frame[1], ipos, iquat)
        return {"pos": ipos, "quat": sp.normalize4(iquat), "mass": mass, "inertia": list(inertia)}

    # ------------------------------------------------ tendons and actuators
    def read_tendons(self, el):
        for t in el:
            if t.tag not in ("fixed", "spatial"):
                continue
            rec = {"name": t.attrib.get("name", ""), "kind": t.tag, "joints": [], "coefs": [], "path": []}
            st = parse_nums(t.attrib.get("stiffness", "0"))
            dm = parse_nums(t.attrib.get("damping", "0"))
            st += [0.0] * (3 - len(st))
            dm += [0.0] * (3 - len(dm))
            rec["stiffness"], rec["stiffpoly"] = st[0], st[1:3]
            rec["damping"], rec["damppoly"] = dm[0], dm[1:3]
            sl = parse_nums(t.attrib["springlength"]) if "springlength" in t.attrib else [-1.0, -1.0]
            if len(sl) == 1:
                sl = [sl[0], sl[0]]
            rec["springlength"] = sl[:2]
            if t.tag == "spatial":
                for p in t:
                    if p.tag == "site":
                        if p.attrib.get("site") not in self.site_names:
                            raise MJCFError("unknown site in spatial tendon")
                        rec["path"].append(("site", self.site_names[p.attrib["site"]]))
                    elif p.tag == "pulley":
                        rec["path"].append(("pulley", float(p.attrib.get("divisor", 1))))
                    elif p.tag == "geom":
                        raise MJCFError("wrapping geoms are not supported")
                if len(rec["path"]) < 2 or rec["path"][0][0] != "site" or rec["path"][-1][0] != "site":
                    raise MJCFError("spatial tendon path must start and end with a site")
                self.tendons.append(rec)
                continue
            for j in t:
                if j.tag != "joint":
                    continue
                name = j.attrib.get("joint")
                if name not in self.joint_names:
                    raise MJCFError(f"unknown joint {name} in tendon")
                rec["joints"].append(name)
                rec["coefs"].append(float(j.attrib.get("coef", 1)))
            self.tendons.append(rec)

    def read_actuators(self, el):
        tendon_names = {t["name"]: i for i, t in enumerate(self.tendons)}
        for a in el:
            if a.tag not in ACTUATOR_TAGS:
                raise MJCFError(f"unsupported actuator {a.tag}")
            s = self.spec_for("actuator", a, "main")
            rec = {"name": a.attrib.get("name", "")}
            if "joint" in a.attrib:
                j = self.joint_names.get(a.attrib["joint"])
                if j is None or j["type"] not in (JNT_HINGE, JNT_SLIDE):
                    raise MJCFError("actuator joint must be a named hinge or slide joint")
                rec["trn"] = ("joint", a.attrib["joint"])
            elif "tendon" in a.attrib:
                if a.attrib["tendon"] not in tendon_names:
                    raise MJCFError("unknown tendon in actuator")
                rec["trn"] = ("tendon", tendon_names[a.attrib["tendon"]])
            else:
                raise MJCFError("actuator needs a joint or tendon")
            gain, bias, dyn = s.str["gaintype"], s.str["biastype"], s.str["dyntype"]
            gainprm, biasprm, dynprm = list(s.num["gainprm"]), list(s.num["biasprm"]), list(s.num["dynprm"])
            if a.tag != "general":
                kp = a.attrib.get("kp")
                kv = a.attrib.get("kv")
                kp = float(kp) if kp is not None else 1.0
                kv = float(kv) if kv is not None else (1.0 if a.tag == "velocity" else 0.0)
                gainprm, biasprm, dynprm = [0.0] * 10, [0.0] * 10, [1.0] + [0.0] * 9
                gain, dyn = "fixed", "none"
                if a.tag == "motor":
                    gainprm[0], bias = 1.0, "none"
                elif a.tag == "position":
                    gainprm[0], bias = kp, "affine"
                    biasprm[1], biasprm[2] = -kp, -kv
                    tc = float(a.attrib.get("timeconst", 0))
                    if tc > 0:
                        dyn, dynprm[0] = "filterexact", tc
                else:  # velocity
                    gainprm[0], bias = kv, "affine"
                    biasprm[2] = -kv
            for name, val, allowed in (("gaintype", gain, ("fixed", "affine")),
                                       ("biastype", bias, ("none", "affine")),
                                       ("dyntype", dyn, ("none", "integrator", "filter", "filterexact"))):
                if val not in allowed:
                    raise MJCFError(f"unsupported {name} {val}")

            def limited(flag, rng):
                v = s.str[flag]
                if v == "auto":
                    return not (rng[0] == 0 and rng[1] == 0)
                return v == "true"

            rec.update(gear=s.num["gear"][0], gaintype=gain, biastype=bias, dyntype=dyn,
                       gainprm=gainprm, biasprm=biasprm, dynprm=dynprm,
                       ctrlrange=list(s.num["ctrlrange"]), forcerange=list(s.num["forcerange"]),
                       actrange=list(s.num["actrange"]))
            rec["ctrllimited"] = limited("ctrllimited", rec["ctrlrange"])
            rec["forcelimited"] = limited("forcelimited", rec["forcerange"])
            rec["actlimited"] = limited("actlimited", rec["actrange"])
            rec["actearly"] = s.str.get("actearly", "false") == "true"
            self.actuators.append(rec)

    SENSORS = {
        # type: (stage, dim, datatype, object attribute)
        "jointpos": ("pos", 1, "real", "joint"), "jointvel": ("vel", 1, "real", "joint"),
        "jointactuatorfrc": ("acc", 1, "real", "joint"), "ballquat": ("pos", 4, "quat", "joint"),
        "ballangvel": ("vel", 3, "real", "joint"), "tendonpos": ("pos", 1, "real", "tendon"),
        "tendonvel": ("vel", 1, "real", "tendon"), "tendonactuatorfrc": ("acc", 1, "real", "tendon"),
        "actuatorpos": ("pos", 1, "real", "actuator"), "actuatorvel": ("vel", 1, "real", "actuator"),
        "actuatorfrc": ("acc", 1, "real", "actuator"), "framepos": ("pos", 3, "real", "frame"),
        "framequat": ("pos", 4, "quat", "frame"), "framexaxis": ("pos", 3, "axis", "frame"),
        "frameyaxis": ("pos", 3, "axis", "frame"), "framezaxis": ("pos", 3, "axis", "frame"),
        "framelinvel": ("vel", 3, "real", "frame"), "frameangvel": ("vel", 3, "real", "frame"),
        "framelinacc": ("acc", 3, "real", "frame"), "frameangacc": ("acc", 3, "real", "frame"),
        "subtreecom": ("pos", 3, "real", "body"), "subtreelinvel": ("vel", 3, "real", "body"),
        "subtreeangmom": ("vel", 3, "real", "body"), "e_potential": ("pos", 1, "real", None),
        "e_kinetic": ("pos", 1, "real", None), "velocimeter": ("vel", 3, "real", "site"),
        "gyro": ("vel", 3, "real", "site"), "accelerometer": ("acc", 3, "real", "site"),
        "force": ("acc", 3, "real", "site"), "torque": ("acc", 3, "real", "site"),
    }

    def frame_object(self, otype, name):
        table = {"body": self.body_names, "xbody": self.body_names, "site": self.site_names,
                 "geom": self.geom_names}
        if otype not in table:
            raise MJCFError(f"unsupported frame object type {otype}")
        if name not in table[otype]:
            raise MJCFError(f"unknown {otype} {name}")
        return table[otype][name]

    def read_sensors(self, el):
        tendon_names = {t["name"]: i for i, t in enumerate(self.tendons) if t["name"]}
        act_names = {a["name"]: i for i, a in enumerate(self.actuators) if a["name"]}
        adr = len(getattr(self, "sensors", [])) and sum(s["dim"] for s in self.sensors)
        self.sensors = getattr(self, "sensors", [])
        for s in el:
            if s.tag not in self.SENSORS:
                raise MJCFError(f"unsupported sensor {s.tag}")
            stage, dim, dtype, obj = self.SENSORS[s.tag]
            rec = {"type": s.tag, "stage": stage, "dim": dim, "datatype": dtype, "adr": adr,
                   "objtype": None, "objid": -1, "reftype": None, "refid": -1,
                   "cutoff": float(s.attrib.get("cutoff", 0))}
            a = s.attrib
            if obj == "joint":
                if a.get("joint") not in self.joint_names:
                    raise MJCFError("unknown joint in sensor")
                rec["objtype"], rec["objid"] = "joint", a["joint"]
            elif obj == "tendon":
                if a.get("tendon") not in tendon_names:
                    raise MJCFError("unknown tendon in sensor")
                rec["objtype"], rec["objid"] = "tendon", tendon_names[a["tendon"]]
            elif obj == "actuator":
                if a.get("actuator") not in act_names:
                    raise MJCFError("unknown actuator in sensor")
                rec["objtype"], rec["objid"] = "actuator", act_names[a["actuator"]]
            elif obj == "body":
                if a.get("body") not in self.body_names:
                    raise MJCFError("unknown body in sensor")
                rec["objtype"], rec["objid"] = "xbody", self.body_names[a["body"]]
            elif obj == "site":
                if a.get("site") not in self.site_names:
                    raise MJCFError("unknown site in sensor")
                rec["objtype"], rec["objid"] = "site", self.site_names[a["site"]]
            elif obj == "frame":
                rec["objtype"] = a.get("objtype")
                rec["objid"] = self.frame_object(rec["objtype"], a.get("objname"))
                if "reftype" in a or "refname" in a:
                    rec["reftype"] = a.get("reftype")
                    rec["refid"] = self.frame_object(rec["reftype"], a.get("refname"))
            if rec["cutoff"] > 0 and dtype in ("quat", "axis"):
                raise MJCFError("cutoff applied to axis or quaternion sensor")
            adr += dim
            self.sensors.append(rec)

    # ------------------------------------------------ body inertia
    def body_inertia(self, b):
        explicit = b.inertial is not None
        infer = self.ifg == "true" or (self.ifg == "auto" and not explicit)
        ipos, iquat, mass, inertia = None, np.array([1.0, 0, 0, 0]), 0.0, [0.0, 0.0, 0.0]
        if explicit:
            ipos, iquat = b.inertial["pos"], b.inertial["quat"]
            mass, inertia = b.inertial["mass"], list(b.inertial["inertia"])
        if infer:
            sel = [g for g in b.geoms if 0 <= g["group"] <= 5 and g["mass"] > sp.EPS]
            if len(sel) == 1:
                g = sel[0]
                ipos, iquat, mass, inertia = g["pos"], g["quat"], g["mass"], list(g["inertia"])
            elif len(sel) > 1:
                mass = sum(g["mass"] for g in sel)
                if mass < sp.EPS:
                    raise MJCFError("body mass is too small")
                com = sum(g["mass"] * g["pos"] for g in sel) / mass
                full = np.zeros((3, 3))
                for g in sel:
                    R = sp.quat2mat(g["quat"])
                    full += R @ np.diag(g["inertia"]) @ R.T
                    d = g["pos"] - com
                    full += g["mass"] * (float(d @ d) * np.eye(3) - np.outer(d, d))
                ipos = com
                iquat, inertia = principal(full)
        if ipos is None:
            ipos, iquat = b.pos.copy(), b.quat.copy()
        mass = max(mass, self.boundmass)
        inertia = [max(x, self.boundinertia) for x in inertia]
        if mass < 0 or min(inertia) < 0:
            raise MJCFError("mass and inertia cannot be negative")
        A, B, C = inertia
        if A + B < C or A + C < B or B + C < A:
            raise MJCFError("inertia must satisfy A + B >= C")
        return np.asarray(ipos, float), sp.normalize4(iquat), float(mass), np.array(inertia, float)

    # ------------------------------------------------ assemble the model
    def build(self):
        m = Model()
        m.opt = self.opt
        nb = len(self.bodies)
        m.nbody = nb
        m.body_parentid = np.array([b.parent for b in self.bodies], int)
        m.body_parentid[0] = 0
        m.body_pos = np.array([b.pos for b in self.bodies], float)
        m.body_quat = np.array([b.quat if b.quat[0] >= 0 else -b.quat for b in self.bodies], float)
        m.body_ipos = np.zeros((nb, 3))
        m.body_iquat = np.tile([1.0, 0, 0, 0], (nb, 1))
        m.body_mass = np.zeros(nb)
        m.body_inertia = np.zeros((nb, 3))
        m.body_gravcomp = np.array([b.gravcomp for b in self.bodies], float)
        for b in self.bodies[1:]:
            ipos, iquat, mass, inertia = self.body_inertia(b)
            m.body_ipos[b.id], m.body_iquat[b.id] = ipos, iquat
            m.body_mass[b.id], m.body_inertia[b.id] = mass, inertia
        m.body_rootid = np.zeros(nb, int)
        for b in self.bodies[1:]:
            m.body_rootid[b.id] = b.id if b.parent == 0 else m.body_rootid[b.parent]

        # joints and dofs
        jt, jb, jq, jd, jpos, jaxis, jstiff, jspoly = [], [], [], [], [], [], [], []
        qpos0, qspring = [], []
        dof_body, dof_jnt, dof_parent, dof_arm, dof_damp, dof_dpoly = [], [], [], [], [], []
        body_jntadr = np.full(nb, -1)
        body_jntnum = np.zeros(nb, int)
        body_dofadr = np.full(nb, -1)
        body_dofnum = np.zeros(nb, int)
        lastdof = np.full(nb, -1)
        self.jnt_index = {}
        for b in self.bodies[1:]:
            lastdof[b.id] = lastdof[b.parent]
            if any(j["type"] == JNT_FREE for j in b.joints):
                if len(b.joints) != 1 or b.parent != 0:
                    raise MJCFError("free joint must be the only joint of a child of the world body")
            hasball = False
            for j in b.joints:
                if j["type"] in (JNT_BALL, JNT_HINGE) and hasball:
                    raise MJCFError("ball followed by rotation")
                hasball = hasball or j["type"] == JNT_BALL
            if b.joints:
                body_jntadr[b.id] = len(jt)
                body_jntnum[b.id] = len(b.joints)
                body_dofadr[b.id] = len(dof_body)
            for j in b.joints:
                jid = len(jt)
                if j["name"]:
                    self.jnt_index[j["name"]] = jid
                jt.append(j["type"])
                jb.append(b.id)
                jq.append(len(qpos0))
                jd.append(len(dof_body))
                jpos.append(j["pos"])
                jaxis.append(j["axis"])
                jstiff.append(j["stiffness"])
                jspoly.append(j["stiffpoly"])
                if j["type"] == JNT_FREE:
                    qpos0 += list(b.pos) + list(b.quat)
                    qspring += list(b.pos) + list(b.quat)
                    ndof = 6
                elif j["type"] == JNT_BALL:
                    qpos0 += [1.0, 0, 0, 0]
                    qspring += [1.0, 0, 0, 0]
                    ndof = 3
                else:
                    qpos0.append(j["ref"])
                    qspring.append(j["springref"])
                    ndof = 1
                for _ in range(ndof):
                    dof_body.append(b.id)
                    dof_jnt.append(jid)
                    dof_parent.append(lastdof[b.id])
                    lastdof[b.id] = len(dof_body) - 1
                    dof_arm.append(j["armature"])
                    dof_damp.append(j["damping"])
                    dof_dpoly.append(j["damppoly"])
            body_dofnum[b.id] = (len(dof_body) - body_dofadr[b.id]) if b.joints else 0
            if body_dofnum[b.id] > 6:
                raise MJCFError("more than 6 dofs in body")
        m.njnt, m.nq, m.nv = len(jt), len(qpos0), len(dof_body)
        m.jnt_type = np.array(jt, int)
        m.jnt_bodyid = np.array(jb, int)
        m.jnt_qposadr = np.array(jq, int)
        m.jnt_dofadr = np.array(jd, int)
        m.jnt_pos = np.array(jpos, float).reshape(-1, 3)
        m.jnt_axis = np.array(jaxis, float).reshape(-1, 3)
        m.jnt_stiffness = np.array(jstiff, float)
        m.jnt_stiffnesspoly = np.array(jspoly, float).reshape(-1, 2)
        m.qpos0 = np.array(qpos0, float)
        m.qpos_spring = np.array(qspring, float)
        m.dof_bodyid = np.array(dof_body, int)
        m.dof_jntid = np.array(dof_jnt, int)
        m.dof_parentid = np.array(dof_parent, int)
        m.dof_armature = np.array(dof_arm, float)
        m.dof_damping = np.array(dof_damp, float)
        m.dof_dampingpoly = np.array(dof_dpoly, float).reshape(-1, 2)
        m.body_jntadr, m.body_jntnum = body_jntadr, body_jntnum
        m.body_dofadr, m.body_dofnum = body_dofadr, body_dofnum
        m.body_subtreemass = m.body_mass.copy()
        for i in range(nb - 1, 0, -1):
            m.body_subtreemass[m.body_parentid[i]] += m.body_subtreemass[i]

        # weld roots: nearest ancestor (inclusive) that has joints
        m.body_weldid = np.zeros(nb, int)
        for b in self.bodies[1:]:
            m.body_weldid[b.id] = b.id if b.joints else m.body_weldid[b.parent]

        # sites and geoms
        m.nsite = len(self.site_list)
        m.site_bodyid = np.array([b for b, _ in self.site_list], int)
        m.site_pos = np.array([s["pos"] for _, s in self.site_list], float).reshape(-1, 3)
        m.site_quat = np.array([s["quat"] for _, s in self.site_list], float).reshape(-1, 4)
        m.ngeom = len(self.geom_list)
        m.geom_bodyid = np.array([b for b, _ in self.geom_list], int)
        m.geom_pos = np.array([g["pos"] for _, g in self.geom_list], float).reshape(-1, 3)
        m.geom_quat = np.array([g["quat"] for _, g in self.geom_list], float).reshape(-1, 4)

        # tendons
        m.ntendon = len(self.tendons)
        m.tendon_spatial = [t["kind"] == "spatial" for t in self.tendons]
        m.tendon_path = [t["path"] for t in self.tendons]
        m.tendon_joints = []
        for t in self.tendons:
            m.tendon_joints.append([(self.jnt_index[n], c) for n, c in zip(t["joints"], t["coefs"])])
        m.tendon_stiffness = np.array([t["stiffness"] for t in self.tendons], float)
        m.tendon_stiffnesspoly = np.array([t["stiffpoly"] for t in self.tendons], float).reshape(-1, 2)
        m.tendon_damping = np.array([t["damping"] for t in self.tendons], float)
        m.tendon_dampingpoly = np.array([t["damppoly"] for t in self.tendons], float).reshape(-1, 2)
        m.tendon_lengthspring = np.array([t["springlength"] for t in self.tendons], float).reshape(-1, 2)

        # actuators
        acts = self.actuators
        m.nu = len(acts)
        m.actuator_trntype = np.array([0 if a["trn"][0] == "joint" else 1 for a in acts], int)
        m.actuator_trnid = np.array([self.jnt_index[a["trn"][1]] if a["trn"][0] == "joint" else a["trn"][1]
                                     for a in acts], int)
        m.actuator_gear = np.array([a["gear"] for a in acts], float)
        dyn_code = {"none": 0, "integrator": 1, "filter": 2, "filterexact": 3}
        m.actuator_dyntype = np.array([dyn_code[a["dyntype"]] for a in acts], int)
        m.actuator_gaintype = np.array([0 if a["gaintype"] == "fixed" else 1 for a in acts], int)
        m.actuator_biastype = np.array([0 if a["biastype"] == "none" else 1 for a in acts], int)
        m.actuator_dynprm = np.array([a["dynprm"] for a in acts], float).reshape(-1, 10)
        m.actuator_gainprm = np.array([a["gainprm"] for a in acts], float).reshape(-1, 10)
        m.actuator_biasprm = np.array([a["biasprm"] for a in acts], float).reshape(-1, 10)
        m.actuator_ctrllimited = np.array([a["ctrllimited"] for a in acts], bool)
        m.actuator_ctrlrange = np.array([a["ctrlrange"] for a in acts], float).reshape(-1, 2)
        m.actuator_forcelimited = np.array([a["forcelimited"] for a in acts], bool)
        m.actuator_forcerange = np.array([a["forcerange"] for a in acts], float).reshape(-1, 2)
        m.actuator_actlimited = np.array([a["actlimited"] for a in acts], bool)
        m.actuator_actrange = np.array([a["actrange"] for a in acts], float).reshape(-1, 2)
        m.actuator_actearly = np.array([a["actearly"] for a in acts], bool)
        adr, na = [], 0
        for a in acts:
            if a["dyntype"] != "none":
                adr.append(na)
                na += 1
            else:
                adr.append(-1)
        m.actuator_actadr = np.array(adr, int)
        m.na = na
        jnt_act = np.zeros(m.njnt, bool)
        for a, tt, tid in zip(acts, m.actuator_trntype, m.actuator_trnid):
            if tt == 0:
                jnt_act[tid] = True
        m.jnt_hasactuator = jnt_act

        # sensors
        sens = getattr(self, "sensors", [])
        for r in sens:
            if r["objtype"] == "joint":
                r["objid"] = self.jnt_index[r["objid"]]
                jt = m.jnt_type[r["objid"]]
                if r["type"].startswith("ball") and jt != JNT_BALL:
                    raise MJCFError("ball sensor on a non-ball joint")
                if not r["type"].startswith("ball") and jt not in (JNT_HINGE, JNT_SLIDE):
                    raise MJCFError("scalar joint sensor on a ball or free joint")
        m.sensors = sens
        m.nsensor = len(sens)
        m.nsensordata = sum(r["dim"] for r in sens)
        m.finalize()

        # spring reference lengths of tendons: computed in the qpos_spring configuration
        if any(ls[0] == -1 and ls[1] == -1 for ls in m.tendon_lengthspring):
            from .model import Data
            from . import engine
            d = Data(m)
            d.qpos = m.qpos_spring.copy()
            engine.kinematics(m, d)
            engine.com_pos(m, d)
            engine.tendon(m, d)
            for i in range(m.ntendon):
                if m.tendon_lengthspring[i, 0] == -1 and m.tendon_lengthspring[i, 1] == -1:
                    m.tendon_lengthspring[i] = d.ten_length[i]
        return m


def compile_xml(text):
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise MJCFError(f"XML parse error: {e}")
    return Compiler(root).run()


def load_model(path):
    with open(path, "r", encoding="utf-8") as f:
        return compile_xml(f.read())
