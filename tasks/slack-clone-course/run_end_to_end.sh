#!/usr/bin/env bash
# End-to-end run: pick a milestone + agent (+ platform/model/config-file),
# validate student-files/spec matches the milestone, then run (agent only,
# no verifier, 50-minute budget).
# Usage: ./run_end_to_end.sh <milestone> <agent> \
#          [--platform PLATFORM] [--model MODEL] [--config-file PATH] \
#          [extra harbor args]
#   agent: "mini-swe" (harbor's built-in mini-swe-agent) or "mini-swe-local"
#          (our vendored mini_swe_agent_local:MiniSweAgentLocal)
#   --platform: the serving platform -- "bedrock" (AWS Bedrock) or "openrouter"
#               (OpenRouter). Defaults to "openrouter". A platform is a way to
#               reach a model; it is NOT a model.
#   --model: the model to run, resolved together with --platform to a config
#            file under agent_llm_config/ and the real litellm model string.
#            Mapped (platform, model) pairs:
#              (bedrock,    deepseek-v3.2)          -- DeepSeek v3.2 on Bedrock
#              (bedrock,    qwen3-32b)              -- Qwen3-32B on Bedrock
#              (bedrock,    nemotron-super-3-120b)  -- Nemotron-super-3-120B on Bedrock
#              (bedrock,    gpt-5.6-luna)           -- GPT 5.6 Luna on Bedrock (Converse)
#              (openrouter, deepseek-v4-flash-0731) -- DeepSeek v4 Flash on OR
#            Required unless --config-file is given. For bedrock, each model uses
#            its own inference-profile ARN, BEDROCK_ARN_<MODEL> (set in dev.env),
#            e.g. BEDROCK_ARN_GPT_5_6_LUNA -- required, no fallback.
#   --config-file: an explicit config file path, bypassing the (platform, model)
#                  mapping table entirely. If given, --model must still be
#                  supplied too (as the real litellm model string for harbor's
#                  -m), but is not looked up in the table; --platform is ignored.
#
# Credentials, by platform (checked after the real model string is known):
#   * bedrock    -> AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION (and
#                   AWS_SESSION_TOKEN if using temporary creds) must be set in
#                   the environment (e.g. via dev.env). They are forwarded into
#                   the trial container via --ae, because the agent runs litellm
#                   *inside* the container where ~/.aws is not present.
#   * openrouter -> OPENROUTER_API_KEY must be set.
#   * openai     -> OPENAI_API_KEY must be set (direct OpenAI API, model gpt-5.6-luna).
# Output: <task>/jobs/<timestamp>/ with the trajectory and an /app snapshot.
#
# Delegates the actual symlinking of environment/spec and the harbor
# invocation to ./run_milestone_with_other_args_set.sh, which is the one place
# that manages that symlink. This script only validates that
# student-files/spec (the student-facing editing surface) already points at
# the requested milestone before proceeding -- it does not fix a mismatch for
# you. student-files/run_student_bedrock.sh and run_student_openrouter.sh are thin
# wrappers around this script, each with a fixed agent/model/platform.
set -euo pipefail
TASK="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$TASK/../.." && pwd)"

# AIDEV-NOTE: source dev.env here so the per-model BEDROCK_ARN_<MODEL> vars (and
# OPENROUTER_API_KEY / AWS creds) are always present, whether this script is run
# directly or via a student wrapper. Each --model resolves to its own
# BEDROCK_ARN_<MODEL> (no fallback), so --model can never drift from the ARN.
# dev.env is resolved script-relative (repo root) so this works from any checkout dir.
DEV_ENV_PATH="$REPO_ROOT/dev.env"
if [ -f "$DEV_ENV_PATH" ]; then
  set -a
  set +u   # dev.env may reference unbound vars (e.g. PYTHONPATH="...:$PYTHONPATH")
  # shellcheck disable=SC1090
  . "$DEV_ENV_PATH"
  set -u
  set +a
fi

USAGE="usage: $(basename "$0") <milestone> <agent> [--platform PLATFORM] [--model MODEL] [--config-file PATH] [extra harbor args]"
MILESTONE="${1:?$USAGE}"
shift
AGENT="${1:?$USAGE}"
shift

EXPECTED_SPEC_TARGET="../course-staff-files/final_task/environment/milestone-specs/milestone-${MILESTONE}-specs"
ACTUAL_SPEC_TARGET="$(readlink "$TASK/student-files/spec" || true)"
if [ "$ACTUAL_SPEC_TARGET" != "$EXPECTED_SPEC_TARGET" ]; then
  echo "student-files/spec does not point at milestone $MILESTONE." >&2
  echo "  expected: $EXPECTED_SPEC_TARGET" >&2
  echo "  actual:   ${ACTUAL_SPEC_TARGET:-<missing or not a symlink>}" >&2
  echo "WERE YOU MODIFYING THE CORRECT SPECS FILE?" >&2
  echo "Fix the spec symlink before running, e.g.:" >&2
  echo "  ln -sfn $EXPECTED_SPEC_TARGET $TASK/student-files/spec" >&2
  exit 1
fi

# Pull --platform/--model/--config-file out of the remaining args; everything
# else passes straight through to harbor untouched.
PLATFORM=""   # no default -- --platform must be given (bedrock|openrouter)
MODEL=""
CONFIG_FILE=""
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --platform) PLATFORM="${2:?--platform needs a value}"; shift 2 ;;
    --model) MODEL="${2:?--model needs a value}"; shift 2 ;;
    --config-file) CONFIG_FILE="${2:?--config-file needs a value}"; shift 2 ;;
    *) ARGS+=("$1"); shift ;;
  esac
done
set -- "${ARGS[@]}"

AGENT_LLM_CONFIG_DIR="$TASK/course-staff-files/final_task/agent_llm_config"

# (platform, model) -> config file + real litellm model string, unless
# --config-file was given explicitly, in which case that mapping is skipped
# entirely (but --model is still required, as-is, for harbor's -m/--model flag).
#
# The real litellm string is "<platform-route>/<model>": openrouter uses
# "openrouter/<vendor>/<model>"; bedrock uses "bedrock/converse/<arn>", where
# the application-inference-profile ARN is what points at the actual model.
if [ -z "$CONFIG_FILE" ]; then
  case "$AGENT" in
    mini-swe|mini-swe-local) : ;;
    *)
      echo "Unknown agent: $AGENT (expected: mini-swe, mini-swe-local)" >&2
      exit 1
      ;;
  esac
  [ -n "$MODEL" ] || { echo "Please specify the model (--model ...)." >&2; exit 1; }
  [ -n "$PLATFORM" ] || { echo "Please specify the platform (--platform bedrock|openrouter|openai)." >&2; exit 1; }
  case "$PLATFORM" in
    openrouter)
      case "$MODEL" in
        deepseek-v4-flash-0731)
          CONFIG_FILE="$AGENT_LLM_CONFIG_DIR/mswea-openrouter-deepseek-v4-flash-0731-reasoning.yaml"
          MODEL="openrouter/deepseek/deepseek-v4-flash-0731"
          ;;
        glm-4.7-flash)
          CONFIG_FILE="$AGENT_LLM_CONFIG_DIR/mswea-openrouter-glm-4.7-flash-no-reasoning.yaml"
          MODEL="openrouter/z-ai/glm-4.7-flash"
          ;;
        glm-4.7-flash-reasoning)
          CONFIG_FILE="$AGENT_LLM_CONFIG_DIR/mswea-openrouter-glm-4.7-flash-reasoning.yaml"
          MODEL="openrouter/z-ai/glm-4.7-flash"
          ;;
        glm-4.7)
          CONFIG_FILE="$AGENT_LLM_CONFIG_DIR/mswea-openrouter-glm-4.7-no-reasoning.yaml"
          MODEL="openrouter/z-ai/glm-4.7"
          ;;
        glm-5.3-flash-reasoning)
          CONFIG_FILE="$AGENT_LLM_CONFIG_DIR/mswea-openrouter-glm-5.3-flash-reasoning.yaml"
          MODEL="openrouter/z-ai/glm-5.3-flash"
          ;;
        gpt-5.6-luna)
          CONFIG_FILE="$AGENT_LLM_CONFIG_DIR/mswea-openrouter-gpt-5.6-luna-no-reasoning.yaml"
          MODEL="openrouter/openai/gpt-5.6-luna"
          ;;
        *)
          echo "No openrouter config for model '$MODEL' -- add it to the mapping" >&2
          echo "table in $(basename "$0") (or pass --config-file explicitly)." >&2
          exit 1
          ;;
      esac
      ;;
    openai)
      # AIDEV-NOTE: direct OpenAI API (litellm "openai/<model>"); needs OPENAI_API_KEY,
      # which harbor forwards into the container itself (PROVIDER_KEYS[openai]).
      case "$MODEL" in
        gpt-5.6-luna)
          CONFIG_FILE="$AGENT_LLM_CONFIG_DIR/mswea-openai-gpt-5.6-luna-no-reasoning.yaml"
          MODEL="openai/gpt-5.6-luna"
          ;;
        *)
          echo "No openai config for model '$MODEL' -- add it to the mapping" >&2
          echo "table in $(basename "$0") (or pass --config-file explicitly)." >&2
          exit 1
          ;;
      esac
      ;;
    bedrock)
      # AIDEV-NOTE: each --model binds to BOTH its config file AND its own
      # inference-profile ARN (BEDROCK_ARN_<MODEL>, set in dev.env), so the model
      # can never drift from the ARN. The per-model ARN is required (no fallback);
      # an unset BEDROCK_ARN_<MODEL> is a hard error below.
      case "$MODEL" in
        deepseek-v3.2)
          CONFIG_FILE="$AGENT_LLM_CONFIG_DIR/mswea-bedrock-deepseek-v32-no-reasoning.yaml"
          MODEL_ARN="${BEDROCK_ARN_DEEPSEEK_V32:-}"
          ;;
        glm-4.7-flash)
          CONFIG_FILE="$AGENT_LLM_CONFIG_DIR/mswea-bedrock-glm-4.7-flash-no-reasoning.yaml"
          MODEL_ARN="${BEDROCK_ARN_GLM_4_7_FLASH:-}"
          ;;
        qwen3-32b)
          CONFIG_FILE="$AGENT_LLM_CONFIG_DIR/mswea-bedrock-qwen3-32b-no-reasoning.yaml"
          MODEL_ARN="${BEDROCK_ARN_QWEN3_32B:-}"
          ;;
        nemotron-super-3-120b)
          CONFIG_FILE="$AGENT_LLM_CONFIG_DIR/mswea-bedrock-nvidia-nemotron-super-3-120b-no-reasoning.yaml"
          MODEL_ARN="${BEDROCK_ARN_NEMOTRON_SUPER_3_120B:-}"
          ;;
        gpt-5.6-luna)
          CONFIG_FILE="$AGENT_LLM_CONFIG_DIR/mswea-bedrock-gpt-5.6-luna-no-reasoning.yaml"
          MODEL_ARN="${BEDROCK_ARN_GPT_5_6_LUNA:-}"
          ;;
        *)
          echo "No bedrock config for model '$MODEL' -- add it to the mapping table." >&2
          exit 1
          ;;
      esac
      # Require the per-model ARN (no fallback), so --model can never drift from the ARN.
      : "${MODEL_ARN:?no ARN for '$MODEL' -- set BEDROCK_ARN_<MODEL> in dev.env}"
      # litellm routes bedrock/converse/<arn> through the Bedrock Converse API.
      MODEL="bedrock/converse/${MODEL_ARN}"
      ;;
    *)
      echo "Unknown platform: $PLATFORM (expected: bedrock, openrouter, openai)" >&2
      exit 1
      ;;
  esac
elif [ -z "$MODEL" ]; then
  echo "Please specify the real litellm model string (--model ...) with --config-file." >&2
  exit 1
fi

# AIDEV-NOTE: bedrock creds must be forwarded via --ae -- the agent runs
# litellm *inside* the trial container (no ~/.aws there), and harbor's Trial
# wires agent extra-env (scoped_exec_env) into every in-container exec. Harbor
# on its own only forwards AWS_ACCESS_KEY_ID (PROVIDER_KEYS[bedrock]), and
# --env-file does not inject vars into the container -- so we forward the full
# key/secret/region set (taken straight from the environment, i.e. dev.env).
# Platform-specific credentials, keyed on the real litellm string so it covers
# both the mapped path and the --config-file bypass. AE_ARGS collects the --ae
# flags; it stays empty for platforms whose single key harbor forwards itself.
AE_ARGS=()
case "$MODEL" in
  bedrock/*)
    : "${AWS_ACCESS_KEY_ID:?set AWS_ACCESS_KEY_ID (e.g. in dev.env) for bedrock models}"
    : "${AWS_SECRET_ACCESS_KEY:?set AWS_SECRET_ACCESS_KEY (e.g. in dev.env) for bedrock models}"
    : "${AWS_REGION:?set AWS_REGION (e.g. in dev.env) for bedrock models}"
    AE_ARGS+=(--ae "AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID")
    AE_ARGS+=(--ae "AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY")
    AE_ARGS+=(--ae "AWS_REGION=$AWS_REGION")
    AE_ARGS+=(--ae "AWS_DEFAULT_REGION=$AWS_REGION")
    # Only present with temporary/role credentials; forward it when set.
    [ -n "${AWS_SESSION_TOKEN:-}" ] && AE_ARGS+=(--ae "AWS_SESSION_TOKEN=$AWS_SESSION_TOKEN")
    ;;
  openrouter/*)
    : "${OPENROUTER_API_KEY:?set OPENROUTER_API_KEY for openrouter models}"
    ;;
  openai/*)
    : "${OPENAI_API_KEY:?set OPENAI_API_KEY (e.g. in dev.env) for openai models}"
    ;;
esac

case "$AGENT" in
  mini-swe)
    exec "$TASK/run_milestone_with_other_args_set.sh" "$MILESTONE" \
      -y \
      -a mini-swe-agent \
      -m "$MODEL" \
      -e docker \
      -o "$TASK/jobs" \
      --disable-verification \
      --agent-kwarg config_file="$CONFIG_FILE" \
      ${AE_ARGS[@]+"${AE_ARGS[@]}"} \
      "$@"
    ;;
  mini-swe-local)
    exec "$TASK/run_milestone_with_other_args_set.sh" "$MILESTONE" \
      -y \
      --agent mini_swe_agent_local:MiniSweAgentLocal \
      --model "$MODEL" \
      -e docker \
      -o "$TASK/jobs" \
      --disable-verification \
      --agent-kwarg config_file="$CONFIG_FILE" \
      --env-file dev.env \
      ${AE_ARGS[@]+"${AE_ARGS[@]}"} \
      "$@"
    ;;
  *)
    echo "Unknown agent: $AGENT (expected: mini-swe, mini-swe-local)" >&2
    exit 1
    ;;
esac
