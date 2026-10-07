#!/usr/bin/env bash
# Fixed student-mode entry point: always runs the vendored mini-swe-local
# agent with GPT 5.6 Luna on the OpenRouter platform. Thin wrapper around
# ../run_end_to_end.sh -- see that script for the milestone/spec validation and
# the full set of platform/model choices.
# Usage: ./run_student_openrouter.sh <milestone> [extra harbor args]
# OPENROUTER_API_KEY comes from DEV_ENV_PATH (sourced below); see
# ../run_end_to_end.sh. Provider routing (azure, no fallbacks) is pinned in the
# model's config file so this matches the bedrock variant's model exactly.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TASK="$(cd "$HERE/.." && pwd)"
# AIDEV-NOTE: resolve dev.env script-relative (repo root = two levels above TASK) so
# this works from any checkout dir, not just /app.
REPO_ROOT="$(cd "$TASK/../.." && pwd)"
DEV_ENV_PATH="$REPO_ROOT/dev.env"

set -a
# shellcheck disable=SC1091
source "$DEV_ENV_PATH"
set +a

MILESTONE="${1:?usage: $(basename "$0") <milestone> [extra harbor args]}"
shift

# AIDEV-NOTE: run (not exec) so we can read the trial's cost_usd from result.json and
# print it afterward, like run_with_format_retry.sh. Stream harbor output live (tee to
# stderr) while capturing it to resolve the job dir; then propagate harbor's exit status.
harbor_status=0
out=$("$TASK/run_end_to_end.sh" "$MILESTONE" mini-swe-local --platform openrouter --model gpt-5.6-luna "$@" 2>&1 | tee /dev/stderr) || harbor_status=$?

job=$(grep -oE "$TASK/jobs/[0-9_-]+" <<<"$out" | tail -1)
if [ -n "$job" ] && [ -f "$job/result.json" ]; then
  cost=$(python3 - "$job" <<'PY' 2>/dev/null || echo 0
import json, sys
print("%.6f" % (json.load(open(sys.argv[1] + "/result.json"))["stats"].get("cost_usd") or 0))
PY
)
  printf 'COST: total=$%s\n' "$cost"
fi

exit "$harbor_status"
