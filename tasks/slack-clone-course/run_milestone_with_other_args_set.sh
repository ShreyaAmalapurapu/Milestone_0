#!/usr/bin/env bash
# Point final_task's /spec at one milestone, then run a real harbor trial
# against it. Unlike environment/build_milestone.sh, this does NOT clean up
# the spec symlink afterward: harbor's own `docker build` happens
# asynchronously as part of the trial, so the symlink must stay in place for
# the whole run (agent + verification), not just one `docker build` step.
#
# Usage: ./run_milestone.sh <milestone> [extra harbor run args...]
#   milestone: one of course-staff-files/final_task/environment/
#              milestone-specs/milestone-<X>-specs suffixes (e.g. 0, 1, all)
#   extra args: passed straight through to `harbor run`, e.g.
#               --agent mini_swe_agent_local:MiniSweAgentLocal
#               --model openrouter/deepseek/deepseek-v4-flash-0731 -y
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
TASK_PATH="tasks/$(basename "$HERE")/course-staff-files/final_task"
ENV_DIR="$HERE/course-staff-files/final_task/environment"

MILESTONE="${1:?usage: $(basename "$0") <milestone> [extra harbor run args...]}"
shift

SPEC_DIR="milestone-specs/milestone-${MILESTONE}-specs"
[ -d "$ENV_DIR/$SPEC_DIR" ] || { echo "No such milestone spec: $ENV_DIR/$SPEC_DIR" >&2; exit 1; }

if [ -e "$ENV_DIR/spec" ] && [ ! -L "$ENV_DIR/spec" ]; then
  echo "spec exists and is not a symlink -- refusing to touch it: $ENV_DIR/spec" >&2
  exit 1
fi

rm -f "$ENV_DIR/spec"
ln -s "$SPEC_DIR" "$ENV_DIR/spec"
echo "spec -> $SPEC_DIR (left in place for the trial; not cleaned up after)"

cd "$REPO_ROOT"
exec uv run harbor run -p "$TASK_PATH" "$@"
