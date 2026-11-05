#!/usr/bin/env python3
"""gen/make_app.py: build the starting tree (harbor/environment/rubocop-base.tar.gz) from rubocop v1.92.0.

usage: python3 -I gen/make_app.py <rubocop git clone at v1.92.0> <Gemfile.lock> <out dir>

Writes <out>/rubocop/ (the starting tree) and <out>/removed.txt. Steps:
  - git archive of tag v1.92.0 (no history)
  - every Layout cop file reduced to its documentation comment and an empty class (registry entries kept)
  - the Layout-only mixins and correctors deleted (their autoload lines stay; nothing else uses them)
  - spec/rubocop/cop/layout/ deleted (it becomes graded material)
  - upstream agent notes (AGENTS.md, CLAUDE.md) and CI config dropped
"""
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile

src, lock, out = sys.argv[1], sys.argv[2], sys.argv[3]
TAG = "v1.92.0"
COMMIT = "4172ce57861498492770675a904a6404324b326f"

head = subprocess.check_output(["git", "-C", src, "rev-parse", TAG + "^{commit}"], text=True).strip()
assert head == COMMIT, head

dst = os.path.join(out, "rubocop")
if os.path.exists(dst):
    shutil.rmtree(dst)
os.makedirs(dst)
data = subprocess.check_output(["git", "-C", src, "archive", "--format=tar", TAG])
with tarfile.open(fileobj=io.BytesIO(data)) as tf:
    tf.extractall(dst)

removed = []

# Layout cops -> documentation + empty class
lay = os.path.join(dst, "lib/rubocop/cop/layout")
for fn in sorted(os.listdir(lay)):
    p = os.path.join(lay, fn)
    lines = open(p).read().split("\n")
    idx = [i for i, l in enumerate(lines) if re.match(r"^      class \w+ < Base( #.*)?$", l)]
    assert len(idx) == 1, fn
    keep = lines[: idx[0]] + [re.sub(r" #.*$", "", lines[idx[0]])]
    stub = "\n".join(keep) + "\n      end\n    end\n  end\nend\n"
    open(p, "w").write(stub)
    removed.append("stub lib/rubocop/cop/layout/" + fn)

# Layout-only support code (used by no cop outside lib/rubocop/cop/layout)
LAYOUT_ONLY = [
    "lib/rubocop/cop/mixin/check_line_breakable.rb",
    "lib/rubocop/cop/mixin/empty_lines_around_body.rb",
    "lib/rubocop/cop/mixin/end_keyword_alignment.rb",
    "lib/rubocop/cop/mixin/first_element_line_break.rb",
    "lib/rubocop/cop/mixin/hash_alignment_styles.rb",
    "lib/rubocop/cop/mixin/multiline_element_indentation.rb",
    "lib/rubocop/cop/mixin/multiline_element_line_breaks.rb",
    "lib/rubocop/cop/mixin/multiline_expression_indentation.rb",
    "lib/rubocop/cop/mixin/multiline_literal_brace_layout.rb",
    "lib/rubocop/cop/mixin/preceding_following_alignment.rb",
    "lib/rubocop/cop/mixin/space_after_punctuation.rb",
    "lib/rubocop/cop/mixin/space_before_punctuation.rb",
    "lib/rubocop/cop/correctors/space_corrector.rb",
    "lib/rubocop/cop/correctors/multiline_literal_brace_corrector.rb",
]
for rel in LAYOUT_ONLY:
    os.remove(os.path.join(dst, rel))
    removed.append("delete " + rel)
    spec = os.path.join(dst, "spec", rel[len("lib/"):].replace(".rb", "_spec.rb"))
    if os.path.exists(spec):
        os.remove(spec)
        removed.append("delete " + os.path.relpath(spec, dst))

shutil.rmtree(os.path.join(dst, "spec/rubocop/cop/layout"))
removed.append("delete spec/rubocop/cop/layout/")
for rel in ["AGENTS.md", "CLAUDE.md", ".github", ".pre-commit-hooks.yaml"]:
    p = os.path.join(dst, rel)
    if os.path.isdir(p):
        shutil.rmtree(p)
    elif os.path.exists(p):
        os.remove(p)
    removed.append("delete " + rel)

shutil.copy(lock, os.path.join(dst, "Gemfile.lock"))
open(os.path.join(out, "removed.txt"), "w").write("\n".join(removed) + "\n")
print(f"{len(removed)} edits; tree at {dst}")
