#!/usr/bin/env bash
# Generate the same keyframed shot with every practical LTX-2.3 quality tier.
# Runs sequentially on one GPU so quality and elapsed-time results are comparable.

set -Eeuo pipefail
umask 022

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
INVOCATION_DIR="$PWD"

GPU="${ONEIROI_LTX_COMPARE_GPU:-0}"
MODES="${ONEIROI_LTX_COMPARE_MODES:-all}"
FPS="${ONEIROI_LTX_COMPARE_FPS:-24}"
DURATION="${ONEIROI_LTX_COMPARE_DURATION:-5}"
NUM_FRAMES="${ONEIROI_LTX_COMPARE_NUM_FRAMES:-}"
SEED="${ONEIROI_LTX_COMPARE_SEED:-42}"
PROMPT_FILE="${ONEIROI_LTX_COMPARE_PROMPT_FILE:-$PROJECT_ROOT/assets/book-transition-prompt.txt}"
PROMPT_OVERRIDE="${ONEIROI_LTX_COMPARE_PROMPT:-}"
FIRST_FRAME="${ONEIROI_LTX_COMPARE_FIRST_FRAME:-$PROJECT_ROOT/assets/head.png}"
LAST_FRAME="${ONEIROI_LTX_COMPARE_LAST_FRAME:-$PROJECT_ROOT/assets/tail.png}"
FIRST_STRENGTH="${ONEIROI_LTX_COMPARE_FIRST_STRENGTH:-1.0}"
LAST_STRENGTH="${ONEIROI_LTX_COMPARE_LAST_STRENGTH:-1.0}"
IMAGE_CRF="${ONEIROI_LTX_COMPARE_IMAGE_CRF:-0}"
QUANTIZATION="${ONEIROI_LTX_COMPARE_QUANTIZATION:-fp8-cast}"
OFFLOAD="${ONEIROI_LTX_COMPARE_OFFLOAD:-none}"
SYNC_MODE="${ONEIROI_LTX_COMPARE_SYNC_MODE:-auto}"
ENHANCE_PROMPT="${ONEIROI_LTX_COMPARE_ENHANCE_PROMPT:-0}"
OVERWRITE="${ONEIROI_LTX_COMPARE_OVERWRITE:-0}"
DRY_RUN=0

LTX_ROOT="${ONEIROI_LTX_ROOT:-/data/oneiroi/ltx-2.3}"
LTX_REPO_DIR="${ONEIROI_LTX_REPO_DIR:-}"
MODEL_DIR="${ONEIROI_LTX_MODEL_DIR:-}"
GEMMA_ROOT="${ONEIROI_LTX_GEMMA_ROOT:-}"
OUTPUT_DIR="${ONEIROI_LTX_COMPARE_OUTPUT_DIR:-}"
FRAMES_EXPLICIT=0
DURATION_EXPLICIT=0

DISTILLED_CHECKPOINT_NAME="ltx-2.3-22b-distilled-1.1.safetensors"
DEV_CHECKPOINT_NAME="ltx-2.3-22b-dev.safetensors"
DISTILLED_LORA_NAME="ltx-2.3-22b-distilled-lora-384-1.1.safetensors"
SPATIAL_UPSAMPLER_NAME="ltx-2.3-spatial-upscaler-x2-1.1.safetensors"

ALL_MODES=(
    distilled-draft
    distilled-720p
    distilled-1080p
    dev-one-stage
    dev-production-720p
    dev-hq-1080p
)
SELECTED_MODES=()
COMMAND=()
MODE_MODULE=""
MODE_LABEL=""
MODE_WIDTH=""
MODE_HEIGHT=""
MODE_STEPS=""

usage() {
    cat <<'EOF'
Usage:
  scripts/compare-ltx-2.3-quality.sh [options]

Generates the same book-opening keyframe transition with multiple LTX-2.3
pipelines. Runs sequentially on one GPU for a fair comparison and writes a TSV
summary containing status, elapsed time, resolution, pipeline, log, and output.

Quality modes:
  distilled-draft          Distilled, 768x512, fastest low-resolution baseline
  distilled-720p           Distilled, 1280x704, practical fast tier
  distilled-1080p          Distilled, 1920x1088, fast pipeline at high resolution
  dev-one-stage            Dev checkpoint, 768x512, official educational baseline
  dev-production-720p      Dev two-stage Euler, 1280x704, production-quality tier
  dev-hq-1080p             Dev two-stage res_2s, 1920x1088, highest-quality tier
  all                       Run every mode above in the listed order (default)

Options:
  -g, --gpu INDEX           Physical GPU index (default: 0)
      --modes LIST          Comma-separated modes or all
      --duration SECONDS    Requested duration, snapped to 8K+1 frames (default: 5)
      --frames COUNT        Exact legal frame count instead of duration
      --fps VALUE           Frame rate (default: 24)
      --seed INTEGER        Shared seed for every mode (default: 42)
  -p, --prompt TEXT         Override the repository book-taking prompt
      --prompt-file PATH    Prompt text file
      --first-frame PATH    Shared first keyframe (default: assets/head.png)
      --last-frame PATH     Shared final keyframe (default: assets/tail.png)
      --no-first-frame      Disable first-frame conditioning
      --no-last-frame       Disable final-frame conditioning
      --first-strength N    First-frame strength in [0,1] (default: 1.0)
      --last-strength N     Last-frame strength in [0,1] (default: 1.0)
      --image-crf N         Conditioning image CRF, 0-51 (default: 0)
      --quantization MODE   none, fp8-cast, or fp8-scaled-mm (default: fp8-cast)
      --offload MODE        none, cpu, or disk (default: none)
      --enhance-prompt      Enable Gemma prompt enhancement for every mode
      --output-dir PATH     Comparison output directory
      --ltx-root PATH       Runtime root (default: /data/oneiroi/ltx-2.3)
      --repo-dir PATH       Official LTX-2 checkout
      --model-dir PATH      LTX-2.3 model directory
      --gemma-root PATH     Gemma model directory
      --sync                Always run uv sync --frozen first
      --no-sync             Require an existing .venv and skip syncing
      --overwrite           Replace existing comparison outputs
      --dry-run             Validate and print every resolved command
      --list-modes          Print quality modes and exit
  -h, --help                Show this help

Examples:
  # All six tiers on GPU 0, same prompt/seed/keyframes
  scripts/compare-ltx-2.3-quality.sh --gpu 0

  # Only the three practical production comparisons
  scripts/compare-ltx-2.3-quality.sh --gpu 2 \
    --modes distilled-720p,dev-production-720p,dev-hq-1080p

  # Print commands without generating
  scripts/compare-ltx-2.3-quality.sh --dry-run
EOF
}

list_modes() {
    printf '%s\n' "${ALL_MODES[@]}"
}

fail() {
    echo "ERROR: $*" >&2
    exit 1
}

require_value() {
    local option="$1"
    local value="${2-}"
    [[ -n "$value" ]] || fail "$option requires a value"
}

is_positive_number() {
    awk -v value="$1" 'BEGIN { exit !(value ~ /^[0-9]+([.][0-9]+)?$/ && value > 0) }'
}

is_unit_interval() {
    awk -v value="$1" 'BEGIN { exit !(value ~ /^[0-9]+([.][0-9]+)?$/ && value >= 0 && value <= 1) }'
}

make_absolute_path() {
    local path="$1"
    case "$path" in
        "~") printf '%s\n' "$HOME" ;;
        "~/"*) printf '%s/%s\n' "$HOME" "${path#\~/}" ;;
        /*) printf '%s\n' "$path" ;;
        *) printf '%s/%s\n' "$INVOCATION_DIR" "$path" ;;
    esac
}

mode_is_valid() {
    local requested="$1"
    local valid
    for valid in "${ALL_MODES[@]}"; do
        [[ "$requested" == "$valid" ]] && return 0
    done
    return 1
}

configure_mode() {
    local mode="$1"
    case "$mode" in
        distilled-draft)
            MODE_MODULE="ltx_pipelines.distilled"
            MODE_LABEL="Distilled draft"
            MODE_WIDTH=768
            MODE_HEIGHT=512
            MODE_STEPS="8 predefined + stage-2 refinement"
            ;;
        distilled-720p)
            MODE_MODULE="ltx_pipelines.distilled"
            MODE_LABEL="Distilled 720p"
            MODE_WIDTH=1280
            MODE_HEIGHT=704
            MODE_STEPS="8 predefined + stage-2 refinement"
            ;;
        distilled-1080p)
            MODE_MODULE="ltx_pipelines.distilled"
            MODE_LABEL="Distilled 1080p"
            MODE_WIDTH=1920
            MODE_HEIGHT=1088
            MODE_STEPS="8 predefined + stage-2 refinement"
            ;;
        dev-one-stage)
            MODE_MODULE="ltx_pipelines.ti2vid_one_stage"
            MODE_LABEL="Dev one-stage baseline"
            MODE_WIDTH=768
            MODE_HEIGHT=512
            MODE_STEPS="30"
            ;;
        dev-production-720p)
            MODE_MODULE="ltx_pipelines.ti2vid_two_stages"
            MODE_LABEL="Dev production 720p"
            MODE_WIDTH=1280
            MODE_HEIGHT=704
            MODE_STEPS="30 + stage-2 refinement"
            ;;
        dev-hq-1080p)
            MODE_MODULE="ltx_pipelines.ti2vid_two_stages_hq"
            MODE_LABEL="Dev HQ 1080p res_2s"
            MODE_WIDTH=1920
            MODE_HEIGHT=1088
            MODE_STEPS="15 res_2s + stage-2 refinement"
            ;;
        *)
            fail "unsupported mode: $mode"
            ;;
    esac
}

while (($#)); do
    case "$1" in
        -g|--gpu)
            require_value "$1" "${2-}"
            GPU="$2"
            shift 2
            ;;
        --modes)
            require_value "$1" "${2-}"
            MODES="$2"
            shift 2
            ;;
        --duration)
            require_value "$1" "${2-}"
            DURATION="$2"
            NUM_FRAMES=""
            DURATION_EXPLICIT=1
            shift 2
            ;;
        --frames)
            require_value "$1" "${2-}"
            NUM_FRAMES="$2"
            DURATION=""
            FRAMES_EXPLICIT=1
            shift 2
            ;;
        --fps)
            require_value "$1" "${2-}"
            FPS="$2"
            shift 2
            ;;
        --seed)
            require_value "$1" "${2-}"
            SEED="$2"
            shift 2
            ;;
        -p|--prompt)
            require_value "$1" "${2-}"
            PROMPT_OVERRIDE="$2"
            PROMPT_FILE=""
            shift 2
            ;;
        --prompt-file)
            require_value "$1" "${2-}"
            PROMPT_FILE="$2"
            PROMPT_OVERRIDE=""
            shift 2
            ;;
        --first-frame)
            require_value "$1" "${2-}"
            FIRST_FRAME="$2"
            shift 2
            ;;
        --last-frame)
            require_value "$1" "${2-}"
            LAST_FRAME="$2"
            shift 2
            ;;
        --no-first-frame)
            FIRST_FRAME=""
            shift
            ;;
        --no-last-frame)
            LAST_FRAME=""
            shift
            ;;
        --first-strength)
            require_value "$1" "${2-}"
            FIRST_STRENGTH="$2"
            shift 2
            ;;
        --last-strength)
            require_value "$1" "${2-}"
            LAST_STRENGTH="$2"
            shift 2
            ;;
        --image-crf)
            require_value "$1" "${2-}"
            IMAGE_CRF="$2"
            shift 2
            ;;
        --quantization)
            require_value "$1" "${2-}"
            QUANTIZATION="$2"
            shift 2
            ;;
        --offload)
            require_value "$1" "${2-}"
            OFFLOAD="$2"
            shift 2
            ;;
        --enhance-prompt)
            ENHANCE_PROMPT=1
            shift
            ;;
        --output-dir)
            require_value "$1" "${2-}"
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --ltx-root)
            require_value "$1" "${2-}"
            LTX_ROOT="$2"
            shift 2
            ;;
        --repo-dir)
            require_value "$1" "${2-}"
            LTX_REPO_DIR="$2"
            shift 2
            ;;
        --model-dir)
            require_value "$1" "${2-}"
            MODEL_DIR="$2"
            shift 2
            ;;
        --gemma-root)
            require_value "$1" "${2-}"
            GEMMA_ROOT="$2"
            shift 2
            ;;
        --sync)
            SYNC_MODE="always"
            shift
            ;;
        --no-sync)
            SYNC_MODE="never"
            shift
            ;;
        --overwrite)
            OVERWRITE=1
            shift
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        --list-modes)
            list_modes
            exit 0
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            fail "unknown argument: $1 (use --help)"
            ;;
    esac
done

[[ "$GPU" =~ ^[0-9]+$ ]] || fail "--gpu must be one non-negative GPU index"
[[ "$SEED" =~ ^-?[0-9]+$ ]] || fail "--seed must be an integer"
is_positive_number "$FPS" || fail "--fps must be a positive number"
is_unit_interval "$FIRST_STRENGTH" || fail "--first-strength must be between 0 and 1"
is_unit_interval "$LAST_STRENGTH" || fail "--last-strength must be between 0 and 1"
[[ "$IMAGE_CRF" =~ ^[0-9]+$ ]] && ((IMAGE_CRF <= 51)) || fail "--image-crf must be from 0 to 51"
[[ "$QUANTIZATION" == "none" || "$QUANTIZATION" == "fp8-cast" || "$QUANTIZATION" == "fp8-scaled-mm" ]] \
    || fail "--quantization must be none, fp8-cast, or fp8-scaled-mm"
[[ "$OFFLOAD" == "none" || "$OFFLOAD" == "cpu" || "$OFFLOAD" == "disk" ]] \
    || fail "--offload must be none, cpu, or disk"
[[ "$SYNC_MODE" == "auto" || "$SYNC_MODE" == "always" || "$SYNC_MODE" == "never" ]] \
    || fail "sync mode must be auto, always, or never"
[[ "$ENHANCE_PROMPT" == "0" || "$ENHANCE_PROMPT" == "1" ]] || fail "enhance prompt must be 0 or 1"
[[ "$OVERWRITE" == "0" || "$OVERWRITE" == "1" ]] || fail "overwrite must be 0 or 1"

if ((FRAMES_EXPLICIT == 1 && DURATION_EXPLICIT == 1)); then
    fail "use either --frames or --duration, not both"
fi

if [[ "$MODES" == "all" ]]; then
    SELECTED_MODES=("${ALL_MODES[@]}")
else
    IFS=',' read -r -a requested_modes <<<"$MODES"
    declare -A seen_modes=()
    for mode in "${requested_modes[@]}"; do
        mode="${mode//[[:space:]]/}"
        [[ -n "$mode" ]] || continue
        mode_is_valid "$mode" || fail "unknown quality mode: $mode"
        if [[ -z "${seen_modes[$mode]+x}" ]]; then
            SELECTED_MODES+=("$mode")
            seen_modes[$mode]=1
        fi
    done
fi
((${#SELECTED_MODES[@]} > 0)) || fail "no quality modes selected"

if [[ -n "$NUM_FRAMES" ]]; then
    [[ "$NUM_FRAMES" =~ ^[0-9]+$ ]] || fail "--frames must be a positive integer"
    ((NUM_FRAMES >= 1 && (NUM_FRAMES - 1) % 8 == 0)) || fail "--frames must satisfy 8K+1"
else
    is_positive_number "$DURATION" || fail "--duration must be a positive number"
    NUM_FRAMES="$(awk -v duration="$DURATION" -v fps="$FPS" 'BEGIN {
        target = duration * fps
        k = int(((target - 1) / 8) + 0.5)
        if (k < 0) k = 0
        print (8 * k) + 1
    }')"
fi
ACTUAL_DURATION="$(awk -v frames="$NUM_FRAMES" -v fps="$FPS" 'BEGIN { printf "%.3f", (frames - 1) / fps }')"

LTX_REPO_DIR="${LTX_REPO_DIR:-$LTX_ROOT/src/LTX-2}"
MODEL_DIR="${MODEL_DIR:-$LTX_ROOT/models/LTX-2.3}"
GEMMA_ROOT="${GEMMA_ROOT:-$LTX_ROOT/models/gemma-3-12b}"
RUN_ID="quality-comparison-$(date +%Y%m%d-%H%M%S)"
OUTPUT_DIR="${OUTPUT_DIR:-$LTX_ROOT/outputs/quality-comparison/$RUN_ID}"

LTX_ROOT="$(make_absolute_path "$LTX_ROOT")"
LTX_REPO_DIR="$(make_absolute_path "$LTX_REPO_DIR")"
MODEL_DIR="$(make_absolute_path "$MODEL_DIR")"
GEMMA_ROOT="$(make_absolute_path "$GEMMA_ROOT")"
OUTPUT_DIR="$(make_absolute_path "$OUTPUT_DIR")"
if [[ -n "$PROMPT_FILE" ]]; then
    PROMPT_FILE="$(make_absolute_path "$PROMPT_FILE")"
fi
if [[ -n "$FIRST_FRAME" ]]; then
    FIRST_FRAME="$(make_absolute_path "$FIRST_FRAME")"
fi
if [[ -n "$LAST_FRAME" ]]; then
    LAST_FRAME="$(make_absolute_path "$LAST_FRAME")"
fi

if [[ -n "$PROMPT_OVERRIDE" ]]; then
    PROMPT="$PROMPT_OVERRIDE"
else
    [[ -f "$PROMPT_FILE" ]] || fail "prompt file not found: $PROMPT_FILE"
    PROMPT="$(<"$PROMPT_FILE")"
fi
[[ -n "${PROMPT//[[:space:]]/}" ]] || fail "prompt must not be empty"

DISTILLED_CHECKPOINT="$MODEL_DIR/$DISTILLED_CHECKPOINT_NAME"
DEV_CHECKPOINT="$MODEL_DIR/$DEV_CHECKPOINT_NAME"
DISTILLED_LORA="$MODEL_DIR/$DISTILLED_LORA_NAME"
SPATIAL_UPSAMPLER="$MODEL_DIR/$SPATIAL_UPSAMPLER_NAME"

[[ -d "$LTX_REPO_DIR" ]] || fail "LTX repository not found: $LTX_REPO_DIR"
[[ -d "$GEMMA_ROOT" ]] || fail "Gemma directory not found: $GEMMA_ROOT"
[[ -z "$FIRST_FRAME" || -f "$FIRST_FRAME" ]] || fail "first frame not found: $FIRST_FRAME"
[[ -z "$LAST_FRAME" || -f "$LAST_FRAME" ]] || fail "last frame not found: $LAST_FRAME"

need_distilled=0
need_dev=0
need_lora=0
need_upsampler=0
for mode in "${SELECTED_MODES[@]}"; do
    case "$mode" in
        distilled-*) need_distilled=1; need_upsampler=1 ;;
        dev-one-stage) need_dev=1 ;;
        dev-production-720p|dev-hq-1080p) need_dev=1; need_lora=1; need_upsampler=1 ;;
    esac
done
((need_distilled == 0)) || [[ -f "$DISTILLED_CHECKPOINT" ]] || fail "missing: $DISTILLED_CHECKPOINT"
((need_dev == 0)) || [[ -f "$DEV_CHECKPOINT" ]] || fail "missing: $DEV_CHECKPOINT"
((need_lora == 0)) || [[ -f "$DISTILLED_LORA" ]] || fail "missing: $DISTILLED_LORA"
((need_upsampler == 0)) || [[ -f "$SPATIAL_UPSAMPLER" ]] || fail "missing: $SPATIAL_UPSAMPLER"

for command_name in awk date mkdir tee uv; do
    command -v "$command_name" >/dev/null 2>&1 || fail "required command is missing: $command_name"
done

if [[ "$SYNC_MODE" == "always" || ("$SYNC_MODE" == "auto" && ! -x "$LTX_REPO_DIR/.venv/bin/python") ]]; then
    if ((DRY_RUN == 1)); then
        printf 'Would run: (cd %q && uv sync --frozen)\n' "$LTX_REPO_DIR"
    else
        echo "=== Sync LTX environment ==="
        (cd "$LTX_REPO_DIR" && uv sync --frozen)
    fi
elif [[ "$SYNC_MODE" == "never" && ! -x "$LTX_REPO_DIR/.venv/bin/python" && "$DRY_RUN" != "1" ]]; then
    fail "missing LTX environment: $LTX_REPO_DIR/.venv"
fi

build_command() {
    local mode="$1"
    local output_path="$2"

    configure_mode "$mode"
    COMMAND=(
        env CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES="$GPU"
        uv run --no-sync python -m "$MODE_MODULE"
    )

    case "$mode" in
        distilled-*)
            COMMAND+=(
                --distilled-checkpoint-path "$DISTILLED_CHECKPOINT"
                --spatial-upsampler-path "$SPATIAL_UPSAMPLER"
            )
            ;;
        dev-one-stage)
            COMMAND+=(
                --checkpoint-path "$DEV_CHECKPOINT"
                --num-inference-steps 30
            )
            ;;
        dev-production-720p)
            COMMAND+=(
                --checkpoint-path "$DEV_CHECKPOINT"
                --distilled-lora "$DISTILLED_LORA" 1.0
                --spatial-upsampler-path "$SPATIAL_UPSAMPLER"
                --num-inference-steps 30
            )
            ;;
        dev-hq-1080p)
            COMMAND+=(
                --checkpoint-path "$DEV_CHECKPOINT"
                --distilled-lora "$DISTILLED_LORA" 1.0
                --distilled-lora-strength-stage-1 0.25
                --distilled-lora-strength-stage-2 0.5
                --spatial-upsampler-path "$SPATIAL_UPSAMPLER"
                --num-inference-steps 15
            )
            ;;
    esac

    COMMAND+=(
        --gemma-root "$GEMMA_ROOT"
        --prompt "$PROMPT"
        --output-path "$output_path"
        --seed "$SEED"
        --height "$MODE_HEIGHT"
        --width "$MODE_WIDTH"
        --num-frames "$NUM_FRAMES"
        --frame-rate "$FPS"
        --offload "$OFFLOAD"
    )

    if [[ "$QUANTIZATION" != "none" ]]; then
        COMMAND+=(--quantization "$QUANTIZATION")
    fi
    if [[ "$ENHANCE_PROMPT" == "1" ]]; then
        COMMAND+=(--enhance-prompt)
    fi
    if [[ -n "$FIRST_FRAME" ]]; then
        COMMAND+=(--image "$FIRST_FRAME" 0 "$FIRST_STRENGTH" "$IMAGE_CRF")
    fi
    if [[ -n "$LAST_FRAME" ]]; then
        COMMAND+=(--image "$LAST_FRAME" "$((NUM_FRAMES - 1))" "$LAST_STRENGTH" "$IMAGE_CRF")
    fi
}

printf '%s\n' \
    "=== LTX-2.3 quality comparison ===" \
    "GPU:          $GPU" \
    "Modes:        ${SELECTED_MODES[*]}" \
    "Frames/FPS:   $NUM_FRAMES @ $FPS (${ACTUAL_DURATION}s)" \
    "Seed:         $SEED" \
    "First frame:  ${FIRST_FRAME:-disabled}" \
    "Last frame:   ${LAST_FRAME:-disabled}" \
    "Quantization: $QUANTIZATION" \
    "Offload:      $OFFLOAD" \
    "Output dir:   $OUTPUT_DIR"

echo "Prompt: $PROMPT"

if ((DRY_RUN == 1)); then
    for mode in "${SELECTED_MODES[@]}"; do
        output_path="$OUTPUT_DIR/$mode.mp4"
        build_command "$mode" "$output_path"
        printf '\n[%s] %s, %sx%s, steps=%s\n' "$mode" "$MODE_LABEL" "$MODE_WIDTH" "$MODE_HEIGHT" "$MODE_STEPS"
        printf '  (cd %q && ' "$LTX_REPO_DIR"
        printf '%q ' "${COMMAND[@]}"
        printf ')\n'
    done
    echo "Dry run complete."
    exit 0
fi

mkdir -p "$OUTPUT_DIR"
SUMMARY_PATH="$OUTPUT_DIR/comparison.tsv"
printf 'mode\tpipeline\twidth\theight\tframes\tfps\tseed\tstatus\texit_code\telapsed_seconds\toutput\tlog\n' >"$SUMMARY_PATH"

failures=0
for mode in "${SELECTED_MODES[@]}"; do
    output_path="$OUTPUT_DIR/$mode.mp4"
    log_path="$OUTPUT_DIR/$mode.log"
    build_command "$mode" "$output_path"

    if [[ -e "$output_path" || -e "$log_path" ]]; then
        if [[ "$OVERWRITE" == "1" ]]; then
            rm -f -- "$output_path" "$log_path"
        else
            fail "comparison output already exists for $mode; use --overwrite or another --output-dir"
        fi
    fi

    printf '\n=== %s: %s (%sx%s, steps=%s) ===\n' \
        "$mode" "$MODE_LABEL" "$MODE_WIDTH" "$MODE_HEIGHT" "$MODE_STEPS"
    printf 'Command: (cd %q && ' "$LTX_REPO_DIR"
    printf '%q ' "${COMMAND[@]}"
    printf ')\n'

    started_epoch="$(date +%s)"
    set +e
    (
        cd "$LTX_REPO_DIR"
        if [[ -x /usr/bin/time ]]; then
            /usr/bin/time -v "${COMMAND[@]}"
        else
            "${COMMAND[@]}"
        fi
    ) 2>&1 | tee "$log_path"
    mode_rc=${PIPESTATUS[0]}
    set -e
    finished_epoch="$(date +%s)"
    elapsed_seconds="$((finished_epoch - started_epoch))"

    if ((mode_rc == 0)) && [[ -s "$output_path" ]]; then
        status="completed"
    else
        status="failed"
        failures=$((failures + 1))
    fi

    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$mode" "$MODE_LABEL" "$MODE_WIDTH" "$MODE_HEIGHT" "$NUM_FRAMES" "$FPS" "$SEED" \
        "$status" "$mode_rc" "$elapsed_seconds" "$output_path" "$log_path" >>"$SUMMARY_PATH"
done

printf '\nComparison summary: %s\n' "$SUMMARY_PATH"
if ((failures > 0)); then
    fail "$failures quality mode(s) failed; successful outputs and logs were preserved"
fi

echo "All requested quality modes completed."
