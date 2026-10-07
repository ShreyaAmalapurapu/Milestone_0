#!/usr/bin/env bash
# Build the final_task image with one milestone's spec baked into /spec.
# Temporarily symlinks spec -> milestone-specs/milestone-<N>-specs, builds,
# then always removes that symlink -- including on a failed build (trap).
#
# harbor's own `docker build` (harbor/environments/docker/docker.py) hardcodes
# environment/Dockerfile and doesn't support picking an alternate Dockerfile,
# so this script re-targets the one real spec symlink instead of maintaining
# separate per-milestone Dockerfiles.
#
# Usage: ./build_milestone.sh [milestone]
#   milestone: one of the milestone-specs/milestone-<X>-specs suffixes
#              (e.g. 0, 1, all). Prompted interactively if omitted.
#
# Note: after this script exits, `spec` does NOT exist. A real `harbor run`
# against final_task needs spec pointed at whichever milestone should be
# live -- re-run this script (or recreate that symlink by hand) before that.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

mapfile -t MILESTONES < <(
  for d in milestone-specs/milestone-*-specs; do
    [ -d "$d" ] || continue
    basename "$d" | sed -E 's/^milestone-(.*)-specs$/\1/'
  done
)
[ "${#MILESTONES[@]}" -gt 0 ] || { echo "No milestone-specs/milestone-*-specs directories found." >&2; exit 1; }

MILESTONE="${1:-}"
if [ -z "$MILESTONE" ]; then
  echo "Which milestone?"
  select MILESTONE in "${MILESTONES[@]}"; do
    [ -n "$MILESTONE" ] && break
  done
fi

SPEC_DIR="milestone-specs/milestone-${MILESTONE}-specs"
[ -d "$SPEC_DIR" ] || { echo "No such milestone spec: $SPEC_DIR" >&2; exit 1; }

if [ -e spec ] && [ ! -L spec ]; then
  echo "spec exists and is not a symlink -- refusing to touch it: $HERE/spec" >&2
  exit 1
fi

rm -f spec
ln -s "$SPEC_DIR" spec
trap 'rm -f "$HERE/spec"' EXIT

echo "Building with spec -> $SPEC_DIR"
docker build -t slack-clone-course "$HERE"
