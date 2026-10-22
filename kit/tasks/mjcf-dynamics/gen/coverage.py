"""Count MJCF features used by a generated set: python3 -I coverage.py <set dir> [<set dir> ...]"""
import collections
import os
import sys
import xml.etree.ElementTree as ET


def features(path):
    f = collections.Counter()
    root = ET.parse(path).getroot()
    comp = root.find("compiler")
    if comp is not None:
        for k, v in comp.attrib.items():
            f[f"compiler.{k}={v}" if k in ("angle", "inertiafromgeom") else f"compiler.{k}"] += 1
    opt = root.find("option")
    if opt is not None:
        for k, v in opt.attrib.items():
            f[f"option.{k}={v}" if k == "integrator" else f"option.{k}"] += 1
        fl = opt.find("flag")
        for k, v in (fl.attrib.items() if fl is not None else []):
            f[f"flag.{k}"] += 1
    if root.find("default") is not None:
        f["default"] += 1
        f["default.nested"] += int(len(root.findall("default/default")) > 0)
    for el in root.iter():
        t = el.tag
        if t == "body":
            js = [j.attrib.get("type", "hinge") for j in el if j.tag == "joint"] + \
                 ["free" for j in el if j.tag == "freejoint"]
            if len(js) > 1:
                f["body.multijoint"] += 1
            for k in ("quat", "axisangle", "euler", "xyaxes", "zaxis", "childclass", "gravcomp"):
                if k in el.attrib:
                    f[f"body.{k}"] += 1
        elif t == "frame":
            f["frame"] += 1
        elif t in ("joint", "freejoint"):
            f[f"joint.{el.attrib.get('type', 'hinge') if t == 'joint' else 'freejoint'}"] += 1
            for k in ("ref", "springref", "class", "armature", "pos"):
                if k in el.attrib:
                    f[f"joint.{k}"] += 1
            for k in ("stiffness", "damping"):
                if k in el.attrib:
                    f[f"joint.{k}{'.poly' if len(el.attrib[k].split()) > 1 else ''}"] += 1
        elif t == "geom":
            f[f"geom.{el.attrib.get('type', 'default')}"] += 1
            for k in ("fromto", "mass", "density", "shellinertia", "class", "quat", "axisangle", "euler",
                      "xyaxes", "zaxis"):
                if k in el.attrib:
                    f[f"geom.{k}"] += 1
        elif t == "inertial":
            f["inertial.full" if "fullinertia" in el.attrib else "inertial.diag"] += 1
        elif t in ("fixed", "spatial"):
            f[f"tendon.{t}"] += 1
            if el.find("pulley") is not None:
                f["tendon.pulley"] += 1
        elif t in ("motor", "position", "velocity", "general") and el.attrib.get("joint", el.attrib.get("tendon")):
            f[f"actuator.{t}"] += 1
            f[f"actuator.on_{'joint' if 'joint' in el.attrib else 'tendon'}"] += 1
            for k in ("ctrlrange", "forcerange", "actrange", "timeconst", "kv", "gaintype", "biastype"):
                if k in el.attrib:
                    f[f"actuator.{k}"] += 1
            if "dyntype" in el.attrib:
                f[f"actuator.dyn.{el.attrib['dyntype']}"] += 1
    for el in root.iter():
        t = el.tag
        if t == "geom":
            for k in ("condim", "priority", "solmix", "solref", "solimp", "margin", "gap", "friction",
                      "fluidshape", "fluidcoef"):
                if k in el.attrib:
                    f[f"geom.{k}"] += 1
        elif t == "joint":
            for k in ("range", "margin", "solreflimit", "solimplimit", "frictionloss", "solreffriction"):
                if k in el.attrib:
                    f[f"joint.{k}"] += 1
        elif t in ("fixed", "spatial"):
            for k in ("range", "frictionloss", "margin"):
                if k in el.attrib:
                    f[f"tendon.{k}"] += 1
            for w in el.findall("geom"):
                f["tendon.wrap.sidesite" if "sidesite" in w.attrib else "tendon.wrap"] += 1
        elif t in ("pair", "exclude", "connect", "weld"):
            f[f"{t}"] += 1
        elif t == "joint" or (t == "tendon" and el.find("..") is not None):
            pass
        elif t in ("muscle", "intvelocity", "damper", "cylinder"):
            f[f"actuator.{t}"] += 1
        if t in ("motor", "position", "velocity", "general"):
            if "site" in el.attrib:
                f["actuator.site" + (".refsite" if "refsite" in el.attrib else "")] += 1
            if "actearly" in el.attrib:
                f["actuator.actearly"] += 1
    eq = root.find("equality")
    for e in (eq if eq is not None else []):
        f[f"equality.{e.tag}"] += 1
    if opt is not None:
        for k in ("solver", "cone"):
            if k in opt.attrib:
                f[f"option.{k}={opt.attrib[k]}"] += 1
        for k in ("impratio", "density", "viscosity", "wind"):
            if k in opt.attrib:
                f[f"option.{k}"] += 1
    sen = root.find("sensor")
    for s in (sen if sen is not None else []):
        f[f"sensor.{s.tag}"] += 1
        if "reftype" in s.attrib:
            f["sensor.ref"] += 1
        if "cutoff" in s.attrib:
            f["sensor.cutoff"] += 1
    return f


sets = sys.argv[1:]
counts = []
for sd in sets:
    tot = collections.Counter()
    nmodels = collections.Counter()
    md = os.path.join(sd, "models")
    for n in sorted(os.listdir(md)):
        fe = features(os.path.join(md, n))
        tot.update(fe)
        nmodels.update({k: 1 for k in fe})
    counts.append(nmodels)
keys = sorted(set().union(*counts))
print("feature".ljust(34) + "".join(os.path.basename(s.rstrip("/")).rjust(10) for s in sets) + "   (models using it)")
for k in keys:
    print(k.ljust(34) + "".join(str(c.get(k, 0)).rjust(10) for c in counts))
