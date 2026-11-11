"""manifest.py <tree> > base.manifest: SHA-256 of each file's content and of its relative path."""
import hashlib, os, sys
root = sys.argv[1]
rows = []
for d, dirs, files in os.walk(root):
    for n in files:
        p = os.path.join(d, n)
        rel = os.path.relpath(p, root)
        h = hashlib.sha256(open(p, "rb").read()).hexdigest()
        rows.append(f"{h}  {hashlib.sha256(rel.encode('utf-8', 'surrogateescape')).hexdigest()}\n")
sys.stdout.write("".join(sorted(rows)))
