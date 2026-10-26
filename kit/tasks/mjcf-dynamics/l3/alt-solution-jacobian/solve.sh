#!/usr/bin/env bash
# l3 alt-solution-jacobian: a different but equally valid implementation. The mass matrix is assembled from body
# Jacobians (sum of J' m J + Jr' I Jr) instead of the composite-rigid-body recursion, linear solves use a hand-written
# Cholesky factorization, principal inertia axes are sorted ascending with the opposite quaternion sign, and body
# quaternions are canonicalized to w >= 0. Must reach the ceiling (1.0).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
rm -rf /app/mjlite && mkdir -p /app/mjlite && cp "$HERE"/mjlite/*.py /app/mjlite/
