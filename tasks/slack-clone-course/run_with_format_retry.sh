#!/usr/bin/env bash
# Bounded fresh-trial retry around run_end_to_end.sh. Re-runs on a RepeatedFormatError
# washout (up to MAX_ATTEMPTS), archives each dud's bad requests, then deletes the dud
# job dir (guarded so nothing outside jobs/ is ever removed).
#
# Usage: run_with_format_retry.sh <milestone>   (model fixed to gpt-5.6-luna)
set -uo pipefail

# --- config ---
# AIDEV-NOTE: derive TASK_DIR from this script's own location so it works from any
# checkout dir, not just /app.
readonly TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly JOBS_DIR="$TASK_DIR/jobs"
readonly ARCHIVE_DIR="$TASK_DIR/duds-archive"
readonly MAX_ATTEMPTS=3
readonly AGENT="mini-swe-local"
readonly PLATFORM="bedrock"
readonly MODEL="gpt-5.6-luna"
readonly MILESTONE="${1:?usage: run_with_format_retry.sh <milestone>}"

# --- helpers ---

# Extract the job dir from harbor's "Results written to <jobs>/<ts>/..." output.
parse_job_dir() {
  grep -oE "$JOBS_DIR/[0-9_-]+" <<<"$1" | tail -1
}

# Run one trial: stream harbor output to the terminal live AND capture it, then
# print ONLY the resolved job dir on stdout for the caller to capture.
run_trial() {
  local out
  out=$("$TASK_DIR/run_end_to_end.sh" "$MILESTONE" "$AGENT" \
          --platform "$PLATFORM" --model "$MODEL" 2>&1 | tee /dev/stderr)
  parse_job_dir "$out"
}

# Echo the run's exit_status from the saved trajectory's final `exit` record
# (empty if unavailable). This one structured field is the sole detection source.
job_exit_status() {
  local job=$1
  [ -n "$job" ] || return 0
  python3 - "$job" <<'PY' 2>/dev/null
import glob, json, sys
for p in glob.glob(sys.argv[1] + "/*/agent/mini-swe-agent.trajectory.json"):
    d = json.load(open(p))
    msgs = d if isinstance(d, list) else (d.get("messages") or d.get("trajectory") or [])
    for m in reversed(msgs):
        if isinstance(m, dict) and (m.get("role") == "exit"):
            print((m.get("extra") or {}).get("exit_status", ""))
            sys.exit()
PY
}

# True iff the run washed out with RepeatedFormatError. Depends ONLY on exit_status;
# any other status (or an unresolved job) is treated as NOT a washout — never retry blindly.
is_format_error_washout() {
  [ "$(job_exit_status "$1")" = "RepeatedFormatError" ]
}

# Save the dud's captured bad requests before its folder is deleted.
archive_bad_requests() {
  local job=$1 attempt=$2 src
  for src in "$job"/*/agent/format_errors.jsonl; do
    [ -f "$src" ] || continue   # only copy if the bad-request log actually exists
    mkdir -p "$ARCHIVE_DIR"
    cp "$src" "$ARCHIVE_DIR/format_errors_attempt${attempt}.jsonl"
  done
}

# Delete a dud job dir, but ONLY if it lives inside JOBS_DIR (safety rail).
delete_job() {
  local job=$1
  case "$job" in
    "$JOBS_DIR"/*) rm -rf "$job" ;;
    *) echo "refusing to delete unexpected path: '$job'" >&2 ;;
  esac
}

# Echo a run's cost_usd (0 if unavailable). MUST be read before a dud is deleted,
# since its result.json goes away with the folder.
job_cost() {
  local job=$1
  python3 - "$job" <<'PY' 2>/dev/null || echo 0
import json, sys
print(json.load(open(sys.argv[1] + "/result.json"))["stats"].get("cost_usd") or 0)
PY
}

# Add two dollar amounts (bash has no float math).
add() { awk "BEGIN{printf \"%.6f\", $1 + $2}"; }

# --- main ---
main() {
  local attempt job cost spent_success=0 spent_wasted=0 total
  for ((attempt = 1; attempt <= MAX_ATTEMPTS; attempt++)); do
    echo "=== attempt $attempt/$MAX_ATTEMPTS: $MODEL on milestone $MILESTONE ==="
    job=$(run_trial)
    cost=$(job_cost "$job")            # capture cost BEFORE any deletion

    if ! is_format_error_washout "$job"; then
      spent_success=$(add "$spent_success" "$cost")
      echo "SUCCESS (attempt $attempt): ${job:-<unresolved job dir>}  [cost \$$cost]"
      report_cost "$spent_success" "$spent_wasted"
      return 0
    fi

    spent_wasted=$(add "$spent_wasted" "$cost")   # dud cost, before deleting it
    echo "attempt $attempt: RepeatedFormatError washout — archiving + deleting $job  [cost \$$cost]"
    archive_bad_requests "$job" "$attempt"
    delete_job "$job"
  done

  echo "FAILED: $MAX_ATTEMPTS consecutive RepeatedFormatError washouts"
  report_cost "$spent_success" "$spent_wasted"
  return 1
}

# Print the money spent, split across the kept run vs the deleted washouts.
report_cost() {
  local success=$1 wasted=$2 total
  total=$(add "$success" "$wasted")
  printf 'COST: successful=$%s  wasted-on-washouts=$%s  total=$%s\n' \
         "$success" "$wasted" "$total"
}

main
