"""Random MJCF model generator for the mjcf-dynamics task (author side only; never ships in the image).

Version 2 (rework round 1): the smooth-dynamics subset of version 1 plus the constraint pipeline. Each model
draws a family that decides which parts of MuJoCo it leans on:

  smooth         contacts and constraints disabled (the version-1 subset)
  joint          joint/tendon limits, dof/tendon friction loss, equality constraints; contacts disabled
  contact_light  contacts among planes, spheres and capsules (+ static world geoms), limits, pairs, excludes
  contact_full   every analytic pair: plane/sphere/capsule/box/cylinder (box-box, capsule-box, ...)
  actuated       muscles, site (refsite) / ball / free transmissions, more shortcuts, wrapping tendons, limits;
                 contacts in 60 % of them
  fluid          inertia-box and ellipsoid fluid forces (density, viscosity, wind), contacts in 60 % of them

Ellipsoids never collide; cylinders collide only with planes and spheres (contype 2, conaffinity 0); spheres
and planes accept both bits. So every contact comes from one of MuJoCo's analytic pair functions, never from
the general convex (GJK/EPA) path.

Usage (pure Python, no MuJoCo needed): gen_model(seed) -> XML string.
"""
import math
import random
import xml.etree.ElementTree as ET

FAMILIES = ["smooth", "joint", "contact_light", "contact_full", "actuated", "fluid"]
FAMILY_W = [0.05, 0.12, 0.25, 0.3, 0.16, 0.12]


def fmt(x):
    s = f"{x:.5g}"
    return "0" if s in ("-0", "0") else s


def vec(xs):
    return " ".join(fmt(x) for x in xs)


def rand_unit(r):
    while True:
        v = [r.gauss(0, 1) for _ in range(3)]
        n = math.sqrt(sum(a * a for a in v))
        if n > 1e-3:
            return [a / n for a in v]


class Gen:
    def __init__(self, seed):
        self.r = random.Random(seed)
        self.seed = seed
        self.degree = True
        self.classes = ["main"]
        self.class_geom = {}       # class -> default geom type or None
        self.joints = []           # (name, type, limited)
        self.nbody = 0
        self.nsite = 0
        self.njoint = 0
        self.ngeomname = 0
        self.body_names = []       # non-world bodies
        self.body_parent = {}      # body name -> parent body name ("world")
        self.site_names = []       # (name, on world)
        self.touch_sites = []
        self.geom_names = []       # named geoms without fromto (frame sensors)
        self.coll_geoms = []       # (name, type, body) named colliding geoms (pairs)
        self.wrap_geoms = []       # (name, type, body, sidesite or None) named spheres/cylinders
        self.act_names = []
        self.ball_names = []
        self.free_names = []
        self.limited_scalar = []
        self.tendon_names = []
        self.limited_tendons = []

    # ---------------- helpers ----------------
    def ang(self, rad):
        return rad * 180 / math.pi if self.degree else rad

    def orientation(self, el, p_none=0.3):
        r = self.r
        if r.random() < p_none:
            return
        kind = r.choice(["quat", "axisangle", "euler", "xyaxes", "zaxis"])
        if kind == "quat":
            el.set("quat", vec([r.gauss(0, 1) for _ in range(4)]))
        elif kind == "axisangle":
            el.set("axisangle", vec([r.gauss(0, 1) for _ in range(3)] + [self.ang(r.uniform(-math.pi, math.pi))]))
        elif kind == "euler":
            el.set("euler", vec([self.ang(r.uniform(-math.pi, math.pi)) for _ in range(3)]))
        elif kind == "xyaxes":
            el.set("xyaxes", vec([r.gauss(0, 1) for _ in range(6)]))
        else:
            el.set("zaxis", vec([r.gauss(0, 1) for _ in range(3)]))

    def pos(self, scale=0.3):
        return [self.r.uniform(-scale, scale) for _ in range(3)]

    def p(self, x):
        return self.r.random() < x

    @property
    def contacts(self):
        return self.fam in ("contact_light", "contact_full") or (self.fam in ("fluid", "actuated") and self.fluid_contacts)

    @property
    def constraints(self):
        return self.fam != "smooth"

    def solref(self):
        r = self.r
        if self.p(0.15):   # direct stiffness / damping form
            return vec([-r.uniform(500, 5000), -r.uniform(5, 60)])
        return vec([r.uniform(0.01, 0.08), r.uniform(0.5, 1.5)])

    def solimp(self):
        r = self.r
        d0 = r.uniform(0.5, 0.95)
        d1 = r.uniform(d0, 0.99)
        vals = [d0, d1, r.uniform(0.0005, 0.02)]
        if self.p(0.5):
            vals += [r.uniform(0.1, 0.9), r.choice([1, 2, 3, r.uniform(1, 4)])]
        return vec(vals)

    # ---------------- top-level ----------------
    def build(self):
        r = self.r
        self.fam = r.choices(FAMILIES, FAMILY_W)[0]
        self.fluid_contacts = self.p(0.6)
        root = ET.Element("mujoco", model=f"m{self.seed}")
        comp = ET.SubElement(root, "compiler")
        self.degree = self.p(0.7)
        comp.set("angle", "degree" if self.degree else "radian")
        if self.p(0.5):
            seq = "".join(r.choice("xyz") for _ in range(3))
            comp.set("eulerseq", "".join(c.upper() if self.p(0.3) else c for c in seq))
        self.ifg = r.choices(["auto", "true", "false"], [0.85, 0.1, 0.05])[0]
        if self.ifg != "auto" or self.p(0.1):
            comp.set("inertiafromgeom", self.ifg)
        if self.p(0.15):
            comp.set("boundmass", fmt(r.uniform(0.05, 0.5)))
        if self.p(0.15):
            comp.set("boundinertia", fmt(r.uniform(1e-4, 5e-3)))

        self.option(root)
        self.defaults(root)
        wb = ET.SubElement(root, "worldbody")
        self.world_geoms(wb)
        if self.p(0.3):
            ET.SubElement(wb, "site", name="ws", pos=vec(self.pos(1)))
            self.nsite += 1
            self.site_names.append(("ws", True))

        self.target_bodies = r.randint(3, 12)
        nroots = 1 if self.p(0.55) else r.randint(2, 3)
        for k in range(nroots):
            if self.nbody >= self.target_bodies and k > 0:
                break
            parent = wb
            if self.p(0.15):
                parent = ET.SubElement(wb, "frame", pos=vec(self.pos(0.3)))
                self.orientation(parent, 0.4)
            self.body(parent, "world", depth=0, root=True, cls=None)

        self.contact_section(root)
        self.tendons(root)
        self.equality(root)
        self.actuators(root)
        self.sensors(root)
        ET.indent(root)
        return ET.tostring(root, encoding="unicode") + "\n"

    def option(self, root):
        r = self.r
        opt = ET.SubElement(root, "option")
        opt.set("timestep", fmt(r.choice([0.001, 0.002, 0.004, 0.005, 0.01])))
        g = r.random()
        if g < 0.12:
            opt.set("gravity", vec([r.uniform(-3, 3), r.uniform(-3, 3), r.uniform(-12, -5)]))
        elif g < 0.15:
            opt.set("gravity", "0 0 0")
        self.integrator = r.choices(["Euler", "RK4", "implicit", "implicitfast"], [0.3, 0.15, 0.25, 0.3])[0]
        if self.integrator != "Euler" or self.p(0.3):
            opt.set("integrator", self.integrator)
        if self.constraints:
            solver = r.choices(["Newton", "CG"], [0.65, 0.35])[0]
            opt.set("solver", solver)
            opt.set("tolerance", "0")
            opt.set("iterations", "100" if solver == "Newton" else "1500")
            opt.set("ls_iterations", "60")
            if self.p(0.4):
                opt.set("cone", "elliptic")
            elif self.p(0.2):
                opt.set("cone", "pyramidal")
            if self.p(0.3):
                opt.set("impratio", fmt(r.uniform(1, 5)))
        if self.fam == "fluid":
            opt.set("density", fmt(r.choice([1.2, r.uniform(50, 1200)])))
            opt.set("viscosity", fmt(r.choice([0, r.uniform(0.001, 2)])))
            if self.p(0.5):
                opt.set("wind", vec([r.uniform(-3, 3) for _ in range(3)]))
        flag = ET.SubElement(opt, "flag")
        if not self.contacts:
            flag.set("contact", "disable")
        if not self.constraints:
            flag.set("constraint", "disable")
        probs = [("gravity", 0.05), ("spring", 0.05), ("damper", 0.05), ("actuation", 0.04),
                 ("eulerdamp", 0.08), ("clampctrl", 0.06)]
        if self.constraints:
            probs += [("equality", 0.05), ("frictionloss", 0.05), ("limit", 0.05)]
        if self.contacts:
            probs += [("filterparent", 0.12)]
        for f, pr in probs:
            if self.p(pr):
                flag.set(f, "disable")

    def world_geoms(self, wb):
        r = self.r
        if self.contacts or self.p(0.5):
            fl = ET.SubElement(wb, "geom", name="floor", type="plane", size="5 5 0.1")
            self.collision_attrs(fl, "plane", world=True)
            self.coll_geoms.append(("floor", "plane", "world"))
            self.geom_names.append("floor")
        if self.contacts and self.p(0.3):
            tp = ET.SubElement(wb, "geom", name="ramp", type="plane", size="2 2 0.1",
                               pos=vec([r.uniform(-0.5, 0.5), r.uniform(-0.5, 0.5), r.uniform(-0.1, 0.1)]))
            tp.set("zaxis", vec([r.uniform(-0.6, 0.6), r.uniform(-0.6, 0.6), 1]))
            self.collision_attrs(tp, "plane", world=True)
            self.coll_geoms.append(("ramp", "plane", "world"))
        if self.contacts and self.p(0.45):
            types = ["sphere", "capsule"] + (["box", "box", "cylinder"] if self.fam != "contact_light" else [])
            for k in range(r.choice([1, 1, 2])):
                t = r.choice(types)
                name = f"wg{k}"
                g = ET.SubElement(wb, "geom", name=name, type=t, size=self.geom_size(t),
                                  pos=vec([r.uniform(-0.6, 0.6), r.uniform(-0.6, 0.6), r.uniform(0.05, 0.5)]))
                self.orientation(g, 0.4)
                self.collision_attrs(g, t, world=True)
                self.coll_geoms.append((name, t, "world"))

    def defaults(self, root):
        if self.p(0.25):
            return
        d = ET.SubElement(root, "default")
        self.default_body(d, "main", 0)

    def default_body(self, d, name, depth):
        r = self.r
        if self.p(0.6):
            j = ET.SubElement(d, "joint")
            if self.p(0.5):
                j.set("damping", fmt(r.uniform(0, 0.5)))
            if self.p(0.4):
                j.set("armature", fmt(r.uniform(0, 0.05)))
            if self.p(0.3):
                j.set("stiffness", fmt(r.uniform(0, 3)))
            if self.p(0.3):
                j.set("axis", vec(rand_unit(r)))
            if self.constraints and self.p(0.2):
                j.set("frictionloss", fmt(r.uniform(0, 0.3)))
            if self.constraints and self.p(0.15):
                j.set("solreflimit", self.solref())
            if depth > 0 and self.p(0.25):
                j.set("type", "slide")
        if self.p(0.6):
            g = ET.SubElement(d, "geom")
            t = None
            if self.p(0.5):
                t = r.choice(self.body_geom_types())
                g.set("type", t)
                g.set("size", self.geom_size(t))
            if self.p(0.4):
                g.set("density", fmt(r.uniform(300, 3000)))
            if self.contacts and self.p(0.3):
                g.set("friction", vec([r.uniform(0.3, 1.5), r.uniform(0.001, 0.05), r.uniform(0.0001, 0.005)]))
            if self.contacts and self.p(0.2):
                g.set("solref", self.solref())
            if self.contacts and self.p(0.2):
                g.set("condim", str(r.choice([1, 3, 4, 6])))
            self.class_geom[name] = t
        if self.p(0.3):
            ET.SubElement(d, "site", size="0.02")
        if self.p(0.3):
            m = ET.SubElement(d, "motor")
            if self.p(0.6):
                m.set("gear", fmt(r.choice([-1, 1]) * r.uniform(0.5, 4)))
            if self.p(0.6):
                m.set("ctrlrange", "-1 1")
        if depth < 3:
            for _ in range(r.choice([0, 1, 1, 2])):
                cname = f"c{len(self.classes)}"
                self.classes.append(cname)
                sub = ET.SubElement(d, "default", **{"class": cname})
                self.default_body(sub, cname, depth + 1)

    def body_geom_types(self):
        if self.fam == "contact_light":
            return ["sphere", "capsule", "capsule", "ellipsoid", "cylinder"]
        if self.fam == "contact_full":
            return ["sphere", "capsule", "box", "box", "cylinder", "ellipsoid"]
        return ["sphere", "capsule", "capsule", "cylinder", "box", "box", "ellipsoid"]

    def geom_size(self, t):
        r = self.r
        if t == "sphere":
            return fmt(r.uniform(0.03, 0.15))
        if t in ("capsule", "cylinder"):
            return vec([r.uniform(0.02, 0.08), r.uniform(0.05, 0.25)])
        return vec([r.uniform(0.03, 0.15) for _ in range(3)])

    def collision_attrs(self, g, t, world=False):
        """contype/conaffinity that keep every pair analytic, plus random contact parameters."""
        r = self.r
        if t == "ellipsoid":
            g.set("contype", "0")
            g.set("conaffinity", "0")
            return
        if t == "cylinder":
            g.set("contype", "2")
            g.set("conaffinity", "0")
        elif t in ("sphere", "plane"):
            g.set("conaffinity", "3")
        if not self.contacts:
            return
        if not world and self.p(0.08):
            g.set("contype", "0")
            g.set("conaffinity", "0")
            return
        if self.p(0.3):
            g.set("condim", str(r.choice([1, 3, 3, 4, 6])))
        if self.p(0.35):
            g.set("friction", vec([r.uniform(0.2, 1.5), r.uniform(0.001, 0.05), r.uniform(0.0001, 0.005)]))
        if self.p(0.2):
            g.set("solref", self.solref())
        if self.p(0.2):
            g.set("solimp", self.solimp())
        if self.p(0.15):
            g.set("margin", fmt(r.uniform(0.002, 0.03)))
            if self.p(0.5):
                g.set("gap", fmt(r.uniform(0, 0.01)))
        if self.p(0.12):
            g.set("priority", str(r.randint(1, 2)))
        if self.p(0.15):
            g.set("solmix", fmt(r.uniform(0.1, 5)))

    # ---------------- bodies ----------------
    def pick_class(self, p=0.3):
        if len(self.classes) > 1 and self.p(p):
            return self.r.choice(self.classes[1:])
        return None

    def body(self, parent, parent_name, depth, root, cls):
        r = self.r
        self.nbody += 1
        name = f"b{self.nbody}"
        b = ET.SubElement(parent, "body", name=name)
        self.body_names.append(name)
        self.body_parent[name] = parent_name
        if root:
            if self.contacts:
                bp = [r.uniform(-0.3, 0.3), r.uniform(-0.3, 0.3), r.uniform(0.0, 0.3)]
            else:
                bp = [r.uniform(-1, 1), r.uniform(-1, 1), r.uniform(0.5, 2)]
        else:
            bp = self.pos(0.3)
        b.set("pos", vec(bp))
        self.orientation(b, 0.4)
        cc = self.pick_class(0.25)
        if cc:
            b.set("childclass", cc)
            cls = cc
        if self.p(0.1):
            b.set("gravcomp", fmt(r.uniform(0, 1)))

        if root and self.p(0.4 if self.contacts else 0.3):
            fname = f"f{self.nbody}"
            if self.p(0.5):
                ET.SubElement(b, "freejoint", name=fname)
            else:
                j = ET.SubElement(b, "joint", type="free", name=fname)
                if self.p(0.3):
                    j.set("damping", fmt(r.uniform(0, 0.2)))
                if self.p(0.2):
                    j.set("stiffness", fmt(r.uniform(0, 2)))
                if self.p(0.3):
                    j.set("armature", fmt(r.uniform(0, 0.02)))
                if self.constraints and self.p(0.15):
                    j.set("frictionloss", fmt(r.uniform(0, 0.2)))
            self.joints.append((fname, "free", False))
            self.free_names.append(fname)
            self.njoint += 1
        else:
            combo = r.choices(
                [[], ["hinge"], ["slide"], ["hinge", "hinge"], ["hinge", "slide"], ["slide", "hinge"],
                 ["ball"], ["slide", "ball"], ["ball", "slide"]],
                [0.06, 0.4, 0.1, 0.1, 0.06, 0.05, 0.13, 0.05, 0.05])[0]
            for t in combo:
                self.joint(b, t, cls)

        explicit = (self.ifg == "false") or self.p(0.15)
        ngeom = r.choice([1, 1, 1, 2, 2, 3])
        if explicit and self.ifg == "false" and self.p(0.3):
            ngeom = r.choice([0, 1])
        for _ in range(ngeom):
            self.geom(b, name, cls)
        if explicit:
            self.inertial(b)
        for _ in range(r.choice([0, 0, 1, 1, 2])):
            self.site(b, cls)

        while self.nbody < self.target_bodies and self.p(0.85 if depth < 5 else 0.3):
            container = b
            if self.p(0.15):
                container = ET.SubElement(b, "frame", pos=vec(self.pos(0.3)))
                self.orientation(container, 0.3)
                fc = self.pick_class(0.3)
                if fc:
                    container.set("childclass", fc)
            self.body(container, name, depth + 1, False, cls)
            if self.p(0.55):
                break
        return b

    def joint(self, b, t, cls):
        r = self.r
        self.njoint += 1
        name = f"j{self.njoint}"
        j = ET.SubElement(b, "joint", name=name)
        jc = self.pick_class(0.25)
        if jc:
            j.set("class", jc)
        if t != "hinge" or self.p(0.7) or jc or cls:
            j.set("type", t)
        if self.p(0.5):
            j.set("pos", vec(self.pos(0.15)))
        if t in ("hinge", "slide") and self.p(0.8):
            j.set("axis", vec([r.gauss(0, 1) for _ in range(3)]))
        if t in ("hinge", "slide") and self.p(0.25):
            j.set("ref", fmt(self.ang(r.uniform(-1, 1)) if t == "hinge" else r.uniform(-0.3, 0.3)))
        if self.p(0.3):
            if self.p(0.3):
                j.set("stiffness", vec([r.uniform(0, 4), r.uniform(-1, 1), r.uniform(0, 1)]))
            else:
                j.set("stiffness", fmt(r.uniform(0, 4)))
            if t in ("hinge", "slide") and self.p(0.5):
                j.set("springref", fmt(self.ang(r.uniform(-1, 1)) if t == "hinge" else r.uniform(-0.3, 0.3)))
        if self.p(0.4):
            if self.p(0.25):
                j.set("damping", vec([r.uniform(0, 0.6), r.uniform(0, 0.3), r.uniform(0, 0.2)]))
            else:
                j.set("damping", fmt(r.uniform(0, 0.6)))
        if self.p(0.3):
            j.set("armature", fmt(r.uniform(0, 0.05)))
        limited = False
        plim = 0.15 if not self.constraints else (0.6 if self.fam == "joint" else 0.4)
        if self.p(plim):
            if t == "ball":
                j.set("range", vec([0, self.ang(r.uniform(0.3, 1.2))]))
            elif t == "hinge":
                lo = r.uniform(0.2, 1.2)
                j.set("range", vec([-self.ang(lo), self.ang(r.uniform(0.2, 1.2))]))
            else:
                j.set("range", vec([-r.uniform(0.05, 0.3), r.uniform(0.05, 0.3)]))
            limited = True
            if self.constraints:
                if self.p(0.2):
                    j.set("margin", fmt(r.uniform(0.01, 0.1) if t == "slide" else self.ang(r.uniform(0.02, 0.2))))
                if self.p(0.25):
                    j.set("solreflimit", self.solref())
                if self.p(0.2):
                    j.set("solimplimit", self.solimp())
            if self.p(0.05):
                j.set("limited", "false")
                limited = False
        if self.constraints and self.p(0.25 if self.fam == "joint" else 0.12):
            j.set("frictionloss", fmt(r.uniform(0.01, 0.5)))
            if self.p(0.2):
                j.set("solreffriction", self.solref())
        self.joints.append((name, t, limited))
        if t == "ball":
            self.ball_names.append(name)
        if limited and t in ("hinge", "slide"):
            self.limited_scalar.append(name)

    def geom(self, b, bname, cls):
        r = self.r
        g = ET.SubElement(b, "geom")
        gc = self.pick_class(0.3)
        if gc:
            g.set("class", gc)
        eff = gc or cls or "main"
        deftype = self.class_geom.get(eff)
        use_default_shape = deftype is not None and self.p(0.4)
        if use_default_shape:
            t = deftype
        else:
            t = r.choice(self.body_geom_types())
            g.set("type", t)
        named = None
        if t in ("capsule", "cylinder", "box", "ellipsoid") and self.p(0.3):
            a = self.pos(0.2)
            bpt = [a[i] + r.uniform(-0.25, 0.25) for i in range(3)]
            g.set("fromto", vec(a + bpt))
            g.set("size", fmt(r.uniform(0.02, 0.07)))
        else:
            if self.p(0.5):
                self.ngeomname += 1
                named = f"g{self.ngeomname}"
                g.set("name", named)
                self.geom_names.append(named)
            if not use_default_shape:
                g.set("size", self.geom_size(t))
            if self.p(0.6):
                g.set("pos", vec(self.pos(0.2)))
            self.orientation(g, 0.5)
        if self.p(0.35):
            g.set("mass", fmt(r.uniform(0.1, 3)))
        elif self.p(0.25):
            g.set("density", fmt(r.uniform(200, 4000)))
        if self.p(0.1):
            g.set("shellinertia", "true")
        if self.p(0.15):
            g.set("rgba", vec([r.random(), r.random(), r.random(), 1]))
        if self.p(0.1):
            g.set("group", str(r.randint(0, 3)))
        self.collision_attrs(g, t)
        if self.fam == "fluid" and self.p(0.5):
            g.set("fluidshape", "ellipsoid")
            if self.p(0.4):
                g.set("fluidcoef", vec([r.uniform(0.1, 1), r.uniform(0.1, 1), r.uniform(0.5, 2),
                                        r.uniform(0.5, 2), r.uniform(0.5, 2)]))
        if named and g.get("contype") != "0":
            self.coll_geoms.append((named, t, bname))
        if named and t in ("sphere", "cylinder") and not g.get("fromto"):
            self.wrap_geoms.append((named, t, bname))

    def inertial(self, b):
        r = self.r
        el = ET.SubElement(b, "inertial", pos=vec(self.pos(0.15)), mass=fmt(r.uniform(0.2, 3)))
        while True:
            I = [r.uniform(0.002, 0.08) for _ in range(3)]
            if I[0] + I[1] >= I[2] * 1.05 and I[0] + I[2] >= I[1] * 1.05 and I[1] + I[2] >= I[0] * 1.05:
                break
        if self.p(0.4):
            q = [r.gauss(0, 1) for _ in range(4)]
            n = math.sqrt(sum(a * a for a in q))
            w, x, y, z = (a / n for a in q)
            R = [[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
                 [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
                 [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]]
            F = [[sum(R[i][k] * I[k] * R[j][k] for k in range(3)) for j in range(3)] for i in range(3)]
            el.set("fullinertia", vec([F[0][0], F[1][1], F[2][2], F[0][1], F[0][2], F[1][2]]))
        else:
            el.set("diaginertia", vec(I))
            self.orientation(el, 0.4)

    def site(self, b, cls):
        r = self.r
        self.nsite += 1
        name = f"s{self.nsite}"
        s = ET.SubElement(b, "site", name=name, pos=vec(self.pos(0.2)))
        self.site_names.append((name, False))
        sc = self.pick_class(0.2)
        if sc:
            s.set("class", sc)
        if self.contacts and self.p(0.35):
            st = r.choice(["sphere", "box", "capsule", "cylinder", "ellipsoid"])
            s.set("type", st)
            if st == "sphere":
                s.set("size", fmt(r.uniform(0.1, 0.4)))
            elif st in ("capsule", "cylinder"):
                s.set("size", vec([r.uniform(0.1, 0.3), r.uniform(0.1, 0.3)]))
            else:
                s.set("size", vec([r.uniform(0.1, 0.4) for _ in range(3)]))
            self.touch_sites.append(name)
        self.orientation(s, 0.5)

    # ---------------- contact section ----------------
    def contact_section(self, root):
        r = self.r
        if not self.contacts:
            return
        pairs = []
        cg = self.coll_geoms
        if len(cg) >= 2 and self.p(0.4):
            ok = {("plane", "sphere"), ("plane", "capsule"), ("plane", "box"), ("plane", "cylinder"),
                  ("sphere", "sphere"), ("sphere", "capsule"), ("sphere", "cylinder"), ("sphere", "box"),
                  ("capsule", "capsule"), ("capsule", "box"), ("box", "box")}
            order = {"plane": 0, "sphere": 2, "capsule": 3, "cylinder": 5, "box": 6}
            for _ in range(r.randint(1, 3)):
                a, b = r.sample(cg, 2)
                if a[2] == b[2]:
                    continue
                ta, tb = sorted((a[1], b[1]), key=lambda t: order[t])
                if (ta, tb) not in ok:
                    continue
                if self.fam == "contact_light" and "box" in (ta, tb):
                    continue
                pairs.append((a[0], b[0]))
        excl = []
        if len(self.body_names) >= 2 and self.p(0.3):
            a, b = r.sample(self.body_names, 2)
            excl.append((a, b))
        if not pairs and not excl:
            return
        ce = ET.SubElement(root, "contact")
        seen = set()
        for a, b in pairs:
            if (a, b) in seen or (b, a) in seen:
                continue
            seen.add((a, b))
            p = ET.SubElement(ce, "pair", geom1=a, geom2=b)
            if self.p(0.5):
                p.set("condim", str(r.choice([1, 3, 4, 6])))
            if self.p(0.5):
                p.set("friction", vec([r.uniform(0.2, 1.5), r.uniform(0.2, 1.5), r.uniform(0.001, 0.05),
                                       r.uniform(0.0001, 0.005), r.uniform(0.0001, 0.005)]))
            if self.p(0.3):
                p.set("solref", self.solref())
            if self.p(0.3):
                p.set("solimp", self.solimp())
            if self.p(0.2):
                p.set("margin", fmt(r.uniform(0.002, 0.03)))
        for a, b in excl:
            ET.SubElement(ce, "exclude", body1=a, body2=b)

    # ---------------- tendons ----------------
    def scalar_joints(self):
        return [n for n, t, _ in self.joints if t in ("hinge", "slide") and n]

    def tendon_limits(self, f, spatial):
        r = self.r
        if not self.constraints:
            return
        if self.p(0.35):
            if spatial:
                lo = r.uniform(0.05, 0.4)
                f.set("range", vec([lo, lo + r.uniform(0.1, 0.8)]))
            else:
                f.set("range", vec([-r.uniform(0.1, 0.8), r.uniform(0.1, 0.8)]))
            self.limited_tendons.append(f.get("name"))
            if self.p(0.25):
                f.set("solreflimit", self.solref())
            if self.p(0.2):
                f.set("margin", fmt(r.uniform(0.005, 0.05)))
        if self.p(0.2):
            f.set("frictionloss", fmt(r.uniform(0.01, 0.4)))

    def tendons(self, root):
        r = self.r
        sj = self.scalar_joints()
        nfixed = 0 if (len(sj) < 2 or self.p(0.5)) else r.choice([1, 1, 2])
        sites = [n for n, _ in self.site_names]
        pspatial = 0.75 if self.fam == "actuated" else 0.4
        nspatial = 0 if (len(sites) < 2 or not self.p(pspatial)) else r.choice([1, 1, 2])
        if nfixed + nspatial == 0:
            return
        te = ET.SubElement(root, "tendon")
        for k in range(nspatial):
            name = f"sp{k}"
            f = ET.SubElement(te, "spatial", name=name)
            if self.p(0.6):
                f.set("stiffness", fmt(r.uniform(0, 20)))
            if self.p(0.6):
                f.set("damping", fmt(r.uniform(0, 2)))
            if self.p(0.25):
                f.set("springlength", fmt(r.uniform(0.1, 0.8)))
            self.tendon_limits(f, True)
            pwrap = 0.7 if self.fam == "actuated" else 0.3
            if self.wrap_geoms and self.p(pwrap):
                # site - geom [sidesite] - site (- geom - site)
                nseg = r.choice([1, 1, 2])
                pick = r.sample(sites, min(len(sites), nseg + 1))
                ET.SubElement(f, "site", site=pick[0])
                for s in pick[1:]:
                    gname = r.choice(self.wrap_geoms)[0]
                    w = ET.SubElement(f, "geom", geom=gname)
                    side = [x for x in sites if x not in pick]
                    if side and self.p(0.5):
                        w.set("sidesite", r.choice(side))
                    ET.SubElement(f, "site", site=s)
            elif len(sites) >= 4 and self.p(0.3):
                pick = r.sample(sites, 4)
                for sn in pick[:2]:
                    ET.SubElement(f, "site", site=sn)
                ET.SubElement(f, "pulley", divisor=fmt(r.choice([2, 3, 0.5])))
                for sn in pick[2:]:
                    ET.SubElement(f, "site", site=sn)
            else:
                for sn in r.sample(sites, min(len(sites), r.choice([2, 2, 3, 4]))):
                    ET.SubElement(f, "site", site=sn)
            self.tendon_names.append(name)
        for k in range(nfixed):
            name = f"t{k}"
            f = ET.SubElement(te, "fixed", name=name)
            if self.p(0.6):
                f.set("stiffness", fmt(r.uniform(0, 5)))
            if self.p(0.6):
                f.set("damping", fmt(r.uniform(0, 1)))
            sl = r.random()
            if sl < 0.25:
                f.set("springlength", fmt(r.uniform(-0.5, 0.5)))
            elif sl < 0.4:
                a = r.uniform(-0.5, 0.2)
                f.set("springlength", vec([a, a + r.uniform(0, 0.4)]))
            self.tendon_limits(f, False)
            for jn in r.sample(sj, min(len(sj), r.choice([2, 2, 3]))):
                ET.SubElement(f, "joint", joint=jn, coef=fmt(r.choice([-1, 1]) * r.uniform(0.2, 2)))
            self.tendon_names.append(name)

    # ---------------- equality ----------------
    def equality(self, root):
        r = self.r
        if not self.constraints:
            return
        pe = {"joint": 0.75, "contact_light": 0.3, "contact_full": 0.25, "actuated": 0.3, "fluid": 0.25}[self.fam]
        if not self.p(pe):
            return
        eq = ET.SubElement(root, "equality")
        sj = self.scalar_joints()
        msites = [n for n, w in self.site_names if not w]
        for k in range(r.choice([1, 1, 2, 3])):
            kinds = ["connect", "weld"]
            if len(sj) >= 1:
                kinds += ["joint", "joint"]
            if self.tendon_names:
                kinds += ["tendon"]
            kind = r.choice(kinds)
            if kind == "connect":
                if len(msites) >= 2 and self.p(0.3):
                    a, b = r.sample(msites, 2)
                    e = ET.SubElement(eq, "connect", site1=a, site2=b)
                else:
                    b1 = r.choice(self.body_names)
                    e = ET.SubElement(eq, "connect", body1=b1, anchor=vec(self.pos(0.2)))
                    if self.p(0.6):
                        others = [x for x in self.body_names if x != b1]
                        if others:
                            e.set("body2", r.choice(others))
            elif kind == "weld":
                b1 = r.choice(self.body_names)
                e = ET.SubElement(eq, "weld", body1=b1)
                others = [x for x in self.body_names if x != b1]
                if others and self.p(0.5):
                    e.set("body2", r.choice(others))
                if self.p(0.3):
                    e.set("anchor", vec(self.pos(0.2)))
                if self.p(0.3):
                    e.set("torquescale", fmt(r.uniform(0.1, 3)))
                if self.p(0.25):
                    q = [r.gauss(0, 1) for _ in range(4)]
                    e.set("relpose", vec(self.pos(0.3) + q))
            elif kind == "joint":
                j1 = r.choice(sj)
                e = ET.SubElement(eq, "joint", joint1=j1)
                others = [x for x in sj if x != j1]
                if others and self.p(0.6):
                    e.set("joint2", r.choice(others))
                if self.p(0.6):
                    e.set("polycoef", vec([r.uniform(-0.3, 0.3), r.uniform(-1.5, 1.5), r.uniform(-0.5, 0.5),
                                           r.uniform(-0.3, 0.3), r.uniform(-0.2, 0.2)]))
            else:
                t1 = r.choice(self.tendon_names)
                e = ET.SubElement(eq, "tendon", tendon1=t1)
                others = [x for x in self.tendon_names if x != t1]
                if others and self.p(0.5):
                    e.set("tendon2", r.choice(others))
                if self.p(0.6):
                    e.set("polycoef", vec([r.uniform(-0.3, 0.6), r.uniform(-1.5, 1.5), r.uniform(-0.5, 0.5),
                                           0, 0]))
            e.set("name", f"eq{k}")
            if self.p(0.35):
                e.set("solref", self.solref())
            if self.p(0.25):
                e.set("solimp", self.solimp())
            if self.p(0.08):
                e.set("active", "false")

    # ---------------- actuators ----------------
    def actuators(self, root):
        r = self.r
        sj = self.scalar_joints()
        targets = [("joint", j) for j in sj] + [("tendon", t) for t in self.tendon_names]
        extra = []
        if self.fam == "actuated" or self.p(0.25):
            msites = [n for n, w in self.site_names if not w]
            extra += [("site", s) for s in msites]
            extra += [("ball", b) for b in self.ball_names] + [("free", f) for f in self.free_names]
        pact = 0.95 if self.fam == "actuated" else 0.6
        if not (targets or extra) or not self.p(pact):
            return
        ac = ET.SubElement(root, "actuator")
        n = r.randint(2, 6) if self.fam == "actuated" else r.randint(1, 4)
        for _ in range(n):
            if extra and (not targets or self.p(0.45)):
                self.special_actuator(ac, r.choice(extra))
            else:
                self.scalar_actuator(ac, r.choice(targets))

    def common(self, a, gear=True):
        r = self.r
        a.set("name", f"a{len(self.act_names)}")
        self.act_names.append(a.get("name"))
        if gear and self.p(0.5):
            a.set("gear", fmt(r.choice([-1, 1]) * r.uniform(0.3, 3)))
        if self.p(0.45):
            a.set("ctrlrange", vec([r.uniform(-1.5, -0.2), r.uniform(0.2, 1.5)]))
        if self.p(0.2):
            a.set("forcerange", vec([-r.uniform(0.5, 3), r.uniform(0.5, 3)]))

    def scalar_actuator(self, ac, target):
        r = self.r
        kind, name = target
        kinds = ["motor", "position", "velocity", "general"]
        w = [0.3, 0.2, 0.12, 0.2]
        if self.fam == "actuated":
            kinds += ["muscle", "intvelocity", "damper", "cylinder"]
            w += [0.35, 0.08, 0.08, 0.06]
        t = r.choices(kinds, w)[0]
        a = ET.SubElement(ac, t, **{kind: name})
        if t == "muscle":
            a.set("name", f"a{len(self.act_names)}")
            self.act_names.append(a.get("name"))
            if kind == "joint":
                lo = r.uniform(-1.2, -0.2)
            else:
                lo = r.uniform(0.05, 0.6)
            a.set("lengthrange", vec([lo, lo + r.uniform(0.3, 1.5)]))
            if self.p(0.5):
                a.set("gear", fmt(r.choice([-1, 1]) * r.uniform(0.5, 2)))
            if self.p(0.5):
                a.set("force", fmt(r.uniform(5, 100)))
            elif self.p(0.4):
                a.set("scale", fmt(r.uniform(50, 400)))
            if self.p(0.4):
                a.set("timeconst", vec([r.uniform(0.005, 0.03), r.uniform(0.02, 0.08)]))
            if self.p(0.3):
                a.set("range", vec([r.uniform(0.5, 0.85), r.uniform(1.05, 1.6)]))
            if self.p(0.3):
                a.set("lmin", fmt(r.uniform(0.3, 0.7)))
                a.set("lmax", fmt(r.uniform(1.4, 1.8)))
            if self.p(0.3):
                a.set("vmax", fmt(r.uniform(0.5, 2)))
                a.set("fvmax", fmt(r.uniform(1.1, 1.6)))
            if self.p(0.3):
                a.set("fpmax", fmt(r.uniform(0.6, 1.8)))
            if self.p(0.2):
                a.set("tausmooth", fmt(r.uniform(0.05, 0.4)))
            return
        if t == "intvelocity":
            self.common(a)
            a.set("kp", fmt(r.uniform(1, 20)))
            a.set("actrange", vec([-r.uniform(0.3, 1.5), r.uniform(0.3, 1.5)]))
            return
        if t == "damper":
            self.common(a)
            a.set("kv", fmt(r.uniform(0.2, 4)))
            a.set("ctrlrange", vec([0, r.uniform(0.5, 2)]))
            return
        if t == "cylinder":
            self.common(a)
            a.set("timeconst", fmt(r.uniform(0.02, 0.3)))
            a.set("area", fmt(r.uniform(0.2, 2)))
            if self.p(0.4):
                a.set("bias", vec([r.uniform(-1, 1), r.uniform(-3, 0), r.uniform(-1, 0)]))
            return
        self.common(a)
        if t == "motor":
            c = self.pick_class(0.4)
            if c:
                a.set("class", c)
        elif t == "position":
            a.set("kp", fmt(r.uniform(1, 30)))
            if self.p(0.4):
                a.set("kv", fmt(r.uniform(0.1, 3)))
            if self.p(0.25):
                a.set("timeconst", fmt(r.uniform(0.02, 0.3)))
        elif t == "velocity":
            a.set("kv", fmt(r.uniform(0.2, 5)))
        else:
            self.general_params(a)

    def general_params(self, a):
        r = self.r
        dyn = r.choice(["none", "integrator", "filter", "filterexact"])
        if dyn != "none" or self.p(0.3):
            a.set("dyntype", dyn)
        if dyn in ("filter", "filterexact"):
            a.set("dynprm", fmt(r.uniform(0.02, 0.5)))
        if self.p(0.5):
            a.set("gaintype", "affine")
            a.set("gainprm", vec([r.uniform(0.5, 3), r.uniform(-1, 1), r.uniform(-1, 1)]))
        elif self.p(0.6):
            a.set("gainprm", fmt(r.uniform(0.5, 3)))
        if self.p(0.5):
            a.set("biastype", "affine")
            a.set("biasprm", vec([r.uniform(-1, 1), -r.uniform(0, 5), -r.uniform(0, 1)]))
        if dyn != "none" and self.p(0.3):
            a.set("actrange", vec([-r.uniform(0.3, 1.5), r.uniform(0.3, 1.5)]))
        if dyn != "none" and self.p(0.2):
            a.set("actearly", "true")

    def special_actuator(self, ac, target):
        r = self.r
        kind, name = target
        t = r.choice(["motor", "motor", "general", "position", "velocity"])
        if kind == "site":
            a = ET.SubElement(ac, t, site=name)
            g = [0.0] * 6
            for i in r.sample(range(6), r.choice([1, 2, 3])):
                g[i] = r.choice([-1, 1]) * r.uniform(0.3, 2)
            a.set("gear", vec(g))
            others = [n for n, w in self.site_names if n != name]
            if others and self.p(0.5):
                a.set("refsite", r.choice(others))
        elif kind == "ball":
            a = ET.SubElement(ac, t, joint=name)
            a.set("gear", vec([r.uniform(-2, 2) for _ in range(3)]))
        else:
            a = ET.SubElement(ac, t, joint=name)
            a.set("gear", vec([r.uniform(-2, 2) for _ in range(6)]))
        self.common(a, gear=False)
        if t == "position":
            a.set("kp", fmt(r.uniform(1, 20)))
        elif t == "velocity":
            a.set("kv", fmt(r.uniform(0.2, 3)))
        elif t == "general":
            self.general_params(a)

    # ---------------- sensors ----------------
    def sensors(self, root):
        r = self.r
        if self.p(0.2):
            return
        sj = self.scalar_joints()
        bodies = self.body_names
        msites = [n for n, w in self.site_names if not w]
        frame_objs = ([("xbody", b) for b in bodies] + [("site", n) for n, _ in self.site_names] +
                      [("geom", g) for g in self.geom_names])
        opts = []
        if sj:
            opts += ["jointpos", "jointvel", "jointactuatorfrc"]
        if self.ball_names:
            opts += ["ballquat", "ballangvel"]
        if self.tendon_names:
            opts += ["tendonpos", "tendonvel", "tendonactuatorfrc"]
        if self.act_names:
            opts += ["actuatorpos", "actuatorvel", "actuatorfrc"]
        opts += ["framepos", "framequat", "framexaxis", "frameyaxis", "framezaxis", "framelinvel",
                 "frameangvel", "framelinacc", "frameangacc", "subtreecom", "subtreelinvel",
                 "subtreeangmom", "e_potential", "e_kinetic"]
        if msites:
            opts += ["velocimeter", "gyro", "accelerometer", "force", "torque"] * 2
        if self.touch_sites:
            opts += ["touch"] * 4
        if self.constraints:
            if self.limited_scalar:
                opts += ["jointlimitpos", "jointlimitvel", "jointlimitfrc"] * 2
            if self.limited_tendons:
                opts += ["tendonlimitpos", "tendonlimitvel", "tendonlimitfrc"] * 2
        se = ET.SubElement(root, "sensor")
        for k in range(r.randint(2, 14)):
            t = r.choice(opts)
            el = ET.SubElement(se, t, name=f"sn{k}")
            if t in ("jointpos", "jointvel", "jointactuatorfrc"):
                el.set("joint", r.choice(sj))
            elif t.startswith("jointlimit"):
                el.set("joint", r.choice(self.limited_scalar))
            elif t.startswith("tendonlimit"):
                el.set("tendon", r.choice(self.limited_tendons))
            elif t in ("ballquat", "ballangvel"):
                el.set("joint", r.choice(self.ball_names))
            elif t.startswith("tendon"):
                el.set("tendon", r.choice(self.tendon_names))
            elif t.startswith("actuator"):
                el.set("actuator", r.choice(self.act_names))
            elif t.startswith("subtree"):
                el.set("body", r.choice(bodies))
            elif t == "touch":
                el.set("site", r.choice(self.touch_sites))
            elif t in ("velocimeter", "gyro", "accelerometer", "force", "torque"):
                el.set("site", r.choice(msites))
            elif t.startswith("frame"):
                invariant = t in ("framepos", "framelinvel", "frameangvel", "framelinacc", "frameangacc")
                if invariant and self.p(0.2):
                    el.set("objtype", "body")
                    el.set("objname", r.choice(bodies))
                else:
                    ot, on = r.choice(frame_objs)
                    el.set("objtype", ot)
                    el.set("objname", on)
                    if t not in ("framelinacc", "frameangacc") and self.p(0.4):
                        rt, rn = r.choice(frame_objs)
                        el.set("reftype", rt)
                        el.set("refname", rn)
            if t not in ("framequat", "ballquat", "framexaxis", "frameyaxis", "framezaxis") and self.p(0.2):
                el.set("cutoff", fmt(r.uniform(0.5, 5)))
            if self.p(0.1):
                el.set("noise", fmt(r.uniform(0.01, 0.1)))


def gen_model(seed):
    return Gen(seed).build()


def family(seed):
    g = Gen(seed)
    g.build()
    return g.fam


if __name__ == "__main__":
    import sys
    print(gen_model(int(sys.argv[1]) if len(sys.argv) > 1 else 0))
