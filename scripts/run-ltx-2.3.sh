#!/usr/bin/env bash
# Configurable single-GPU wrapper for the official LTX-2.3 Distilled pipeline.
#
# The defaults target the H100 layout created by bootstrap-ltx-2.3-h100.sh and
# use this repository's assets/head.png and assets/tail.png as keyframes.

set -Eeuo pipefail
umask 022

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
INVOCATION_DIR="$PWD"

DEFAULT_PROMPT_FILE="$PROJECT_ROOT/assets/book-transition-prompt.txt"
if [[ -f "$DEFAULT_PROMPT_FILE" ]]; then
    DEFAULT_PROMPT="$(<"$DEFAULT_PROMPT_FILE")"
else
    DEFAULT_PROMPT="A woman in white pajamas opens the hidden headboard cabinet, reveals the books, and begins taking one book while the camera and bedroom remain stable."
fi

GPU="${ONEIROI_LTX_GPU:-0}"
QUALITY="${ONEIROI_LTX_QUALITY:-720p}"
ORIENTATION="${ONEIROI_LTX_ORIENTATION:-landscape}"
WIDTH="${ONEIROI_LTX_WIDTH:-}"
HEIGHT="${ONEIROI_LTX_HEIGHT:-}"
FPS="${ONEIROI_LTX_FPS:-24}"
NUM_FRAMES="${ONEIROI_LTX_NUM_FRAMES:-}"
DURATION="${ONEIROI_LTX_DURATION:-5}"
SEED="${ONEIROI_LTX_SEED:-42}"
PROMPT="${ONEIROI_LTX_PROMPT:-$DEFAULT_PROMPT}"
PROMPT_FILE=""
FIRST_FRAME="${ONEIROI_LTX_FIRST_FRAME:-$PROJECT_ROOT/assets/head.png}"
LAST_FRAME="${ONEIROI_LTX_LAST_FRAME:-$PROJECT_ROOT/assets/tail.png}"
FIRST_FRAME_STRENGTH="${ONEIROI_LTX_FIRST_FRAME_STRENGTH:-1.0}"
LAST_FRAME_STRENGTH="${ONEIROI_LTX_LAST_FRAME_STRENGTH:-1.0}"
IMAGE_CRF="${ONEIROI_LTX_IMAGE_CRF:-0}"
QUANTIZATION="${ONEIROI_LTX_QUANTIZATION:-fp8-cast}"
OFFLOAD="${ONEIROI_LTX_OFFLOAD:-none}"
ENHANCE_PROMPT="${ONEIROI_LTX_ENHANCE_PROMPT:-0}"
SYNC_MODE="${ONEIROI_LTX_SYNC_MODE:-auto}"
OUTPUT_PATH="${ONEIROI_LTX_OUTPUT_PATH:-}"
LOG_PATH="${ONEIROI_LTX_LOG_PATH:-}"
MANIFEST_PATH="${ONEIROI_LTX_MANIFEST_PATH:-}"
OVERWRITE="${ONEIROI_LTX_OVERWRITE:-0}"
CUDA_LINK_DIR="${ONEIROI_LTX_CUDA_LINK_DIR:-}"
CUDA_RUNTIME_DIR="${ONEIROI_LTX_CUDA_RUNTIME_DIR:-}"
DRY_RUN=0

LTX_ROOT_OVERRIDE=""
LTX_REPO_DIR_OVERRIDE=""
CHECKPOINT_PATH_OVERRIDE=""
SPATIAL_UPSAMPLER_PATH_OVERRIDE=""
GEMMA_ROOT_OVERRIDE=""
FRAMES_EXPLICIT=0
DURATION_EXPLICIT=0
WIDTH_EXPLICIT=0
HEIGHT_EXPLICIT=0
EXTRA_ARGS=()

usage() {
    cat <<'EOF'
Usage:
  scripts/run-ltx-2.3.sh [options] [-- extra-ltx-arguments...]

Runs the official LTX-2.3 Distilled pipeline on one selected GPU. By default it
uses assets/head.png as frame 0, assets/tail.png as the final frame, generates
about 5 seconds at model-safe 720p, and writes a timestamped MP4 under LTX_ROOT.

Core options:
  -g, --gpu INDEX                 Physical GPU index exposed through CUDA_VISIBLE_DEVICES (default: 0)
  -q, --quality PRESET            draft, 720p, 1080p, or custom (default: 720p)
      --orientation VALUE         landscape or portrait (default: landscape)
      --width PIXELS              Custom width; must be paired with --height and divisible by 64
      --height PIXELS             Custom height; must be paired with --width and divisible by 64
  -p, --prompt TEXT               Generation prompt
      --prompt-file PATH          Read the prompt from a UTF-8 text file
  -o, --output PATH               Output MP4 path
      --overwrite                 Allow replacing an existing output

Timing and reproducibility:
      --duration SECONDS          Requested duration; snapped to a legal 8K+1 frame count (default: 5)
      --frames COUNT              Exact frame count; must satisfy COUNT = 8K+1
      --fps VALUE                 Frame rate (default: 24)
      --seed INTEGER              Random seed (default: 42)

Keyframe conditioning:
      --first-frame PATH          Image used at frame 0 (default: assets/head.png)
      --last-frame PATH           Image used at the final generated frame (default: assets/tail.png)
      --no-first-frame            Disable first-frame conditioning
      --no-last-frame             Disable final-frame conditioning
      --first-strength VALUE      First-frame strength in [0,1] (default: 1.0)
      --last-strength VALUE       Final-frame strength in [0,1] (default: 1.0)
      --image-crf INTEGER         Conditioning image CRF, 0-51; 0 is lossless (default: 0)

Memory and runtime:
      --quantization MODE         none, fp8-cast, or fp8-scaled-mm (default: fp8-cast)
      --offload MODE              none, cpu, or disk (default: none)
      --enhance-prompt            Enable the built-in Gemma prompt enhancer
      --no-enhance-prompt         Disable prompt enhancement (default)
      --sync                      Always run "uv sync --frozen" first
      --no-sync                   Never sync; require an existing LTX .venv
      --dry-run                   Validate and print the resolved command without running it

Model/layout overrides:
      --ltx-root PATH             Runtime root (default: /data/oneiroi/ltx-2.3)
      --repo-dir PATH             Official LTX-2 checkout
      --checkpoint PATH           Distilled checkpoint
      --upsampler PATH            Spatial upsampler checkpoint
      --gemma-root PATH           Gemma model directory
      --log PATH                  Log path
      --manifest PATH             Reproducibility manifest path
  -h, --help                      Show this help

Resolution presets use dimensions accepted by the two-stage pipeline:
  draft:  768x512
  720p:   1280x704   (720 is normalized to the nearest model-safe multiple of 64)
  1080p:  1920x1088 (1080 is normalized to the nearest model-safe multiple of 64)
  portrait swaps width and height.

Environment defaults use the ONEIROI_LTX_* names matching the long options,
for example ONEIROI_LTX_GPU, ONEIROI_LTX_QUALITY, ONEIROI_LTX_DURATION,
ONEIROI_LTX_FIRST_FRAME, ONEIROI_LTX_QUANTIZATION, and ONEIROI_LTX_OFFLOAD.

Examples:
  # Repository book-opening keyframes and prompt, GPU 0, 720p, approximately 5 seconds
  scripts/run-ltx-2.3.sh

  # GPU 3, model-safe 1080p, approximately 8 seconds, CPU offload
  scripts/run-ltx-2.3.sh --gpu 3 --quality 1080p --duration 8 --offload cpu \
    --prompt-file prompts/shot.txt --output /data/oneiroi/outputs/shot-01.mp4

  # Text-to-video without keyframes
  scripts/run-ltx-2.3.sh --no-first-frame --no-last-frame --quality draft

  # Custom portrait output and an explicit final frame
  scripts/run-ltx-2.3.sh --quality custom --width 704 --height 1280 \
    --first-frame assets/head.png --last-frame assets/tail.png
EOF
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
        "~")
            printf '%s\n' "$HOME"
            ;;
        "~/"*)
            printf '%s/%s\n' "$HOME" "${path#\~/}"
            ;;
        /*)
            printf '%s\n' "$path"
            ;;
        *)
            printf '%s/%s\n' "$INVOCATION_DIR" "$path"
            ;;
    esac
}

detect_cuda_library_dirs() {
    local candidate

    if [[ -z "$CUDA_LINK_DIR" ]]; then
        for candidate in /usr/local/cuda/compat /usr/local/cuda-*/compat /usr/local/cuda-*/targets/x86_64-linux/lib/stubs; do
            if [[ -f "$candidate/libcuda.so" ]]; then
                CUDA_LINK_DIR="$candidate"
                break
            fi
        done
    fi

    if [[ -z "$CUDA_RUNTIME_DIR" ]]; then
        for candidate in /usr/lib/x86_64-linux-gnu /lib/x86_64-linux-gnu /usr/lib/wsl/lib; do
            if [[ -f "$candidate/libcuda.so.1" ]]; then
                CUDA_RUNTIME_DIR="$candidate"
                break
            fi
        done
    fi

    [[ -z "$CUDA_LINK_DIR" || -f "$CUDA_LINK_DIR/libcuda.so" ]] \
        || fail "CUDA link directory does not contain libcuda.so: $CUDA_LINK_DIR"
    [[ -z "$CUDA_RUNTIME_DIR" || -f "$CUDA_RUNTIME_DIR/libcuda.so.1" ]] \
        || fail "CUDA runtime directory does not contain libcuda.so.1: $CUDA_RUNTIME_DIR"
}

while (($#)); do
    case "$1" in
        -g|--gpu)
            require_value "$1" "${2-}"
            GPU="$2"
            shift 2
            ;;
        -q|--quality)
            require_value "$1" "${2-}"
            QUALITY="$2"
            shift 2
            ;;
        --orientation)
            require_value "$1" "${2-}"
            ORIENTATION="$2"
            shift 2
            ;;
        --width)
            require_value "$1" "${2-}"
            WIDTH="$2"
            WIDTH_EXPLICIT=1
            shift 2
            ;;
        --height)
            require_value "$1" "${2-}"
            HEIGHT="$2"
            HEIGHT_EXPLICIT=1
            shift 2
            ;;
        -p|--prompt)
            require_value "$1" "${2-}"
            PROMPT="$2"
            shift 2
            ;;
        --prompt-file)
            require_value "$1" "${2-}"
            PROMPT_FILE="$2"
            shift 2
            ;;
        -o|--output)
            require_value "$1" "${2-}"
            OUTPUT_PATH="$2"
            shift 2
            ;;
        --overwrite)
            OVERWRITE=1
            shift
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
            FIRST_FRAME_STRENGTH="$2"
            shift 2
            ;;
        --last-strength)
            require_value "$1" "${2-}"
            LAST_FRAME_STRENGTH="$2"
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
        --no-enhance-prompt)
            ENHANCE_PROMPT=0
            shift
            ;;
        --sync)
            SYNC_MODE="always"
            shift
            ;;
        --no-sync)
            SYNC_MODE="never"
            shift
            ;;
        --ltx-root)
            require_value "$1" "${2-}"
            LTX_ROOT_OVERRIDE="$2"
            shift 2
            ;;
        --repo-dir)
            require_value "$1" "${2-}"
            LTX_REPO_DIR_OVERRIDE="$2"
            shift 2
            ;;
        --checkpoint)
            require_value "$1" "${2-}"
            CHECKPOINT_PATH_OVERRIDE="$2"
            shift 2
            ;;
        --upsampler)
            require_value "$1" "${2-}"
            SPATIAL_UPSAMPLER_PATH_OVERRIDE="$2"
            shift 2
            ;;
        --gemma-root)
            require_value "$1" "${2-}"
            GEMMA_ROOT_OVERRIDE="$2"
            shift 2
            ;;
        --log)
            require_value "$1" "${2-}"
            LOG_PATH="$2"
            shift 2
            ;;
        --manifest)
            require_value "$1" "${2-}"
            MANIFEST_PATH="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            EXTRA_ARGS=("$@")
            break
            ;;
        *)
            fail "unknown argument: $1 (use --help)"
            ;;
    esac
done

[[ "$GPU" =~ ^[0-9]+$ ]] || fail "--gpu must be one non-negative GPU index"
[[ "$ORIENTATION" == "landscape" || "$ORIENTATION" == "portrait" ]] \
    || fail "--orientation must be landscape or portrait"
[[ "$SEED" =~ ^-?[0-9]+$ ]] || fail "--seed must be an integer"
is_positive_number "$FPS" || fail "--fps must be a positive number"
is_unit_interval "$FIRST_FRAME_STRENGTH" || fail "--first-strength must be between 0 and 1"
is_unit_interval "$LAST_FRAME_STRENGTH" || fail "--last-strength must be between 0 and 1"
[[ "$IMAGE_CRF" =~ ^[0-9]+$ ]] && ((IMAGE_CRF <= 51)) || fail "--image-crf must be an integer from 0 to 51"
[[ "$OFFLOAD" == "none" || "$OFFLOAD" == "cpu" || "$OFFLOAD" == "disk" ]] \
    || fail "--offload must be none, cpu, or disk"
[[ "$QUANTIZATION" == "none" || "$QUANTIZATION" == "fp8-cast" || "$QUANTIZATION" == "fp8-scaled-mm" ]] \
    || fail "--quantization must be none, fp8-cast, or fp8-scaled-mm"
[[ "$SYNC_MODE" == "auto" || "$SYNC_MODE" == "always" || "$SYNC_MODE" == "never" ]] \
    || fail "sync mode must be auto, always, or never"
[[ "$ENHANCE_PROMPT" == "0" || "$ENHANCE_PROMPT" == "1" ]] \
    || fail "ONEIROI_LTX_ENHANCE_PROMPT must be 0 or 1"
[[ "$OVERWRITE" == "0" || "$OVERWRITE" == "1" ]] \
    || fail "ONEIROI_LTX_OVERWRITE must be 0 or 1"

if ((FRAMES_EXPLICIT == 1 && DURATION_EXPLICIT == 1)); then
    fail "use either --frames or --duration, not both"
fi

if [[ -n "$PROMPT_FILE" ]]; then
    [[ -f "$PROMPT_FILE" ]] || fail "prompt file not found: $PROMPT_FILE"
    PROMPT="$(<"$PROMPT_FILE")"
fi
[[ -n "${PROMPT//[[:space:]]/}" ]] || fail "prompt must not be empty"

if ((WIDTH_EXPLICIT != HEIGHT_EXPLICIT)); then
    fail "--width and --height must be provided together"
fi

if ((WIDTH_EXPLICIT == 1)) || [[ -n "$WIDTH" || -n "$HEIGHT" ]]; then
    [[ -n "$WIDTH" && -n "$HEIGHT" ]] || fail "custom width and height must both be set"
    QUALITY="custom"
else
    case "$QUALITY" in
        draft)
            WIDTH=768
            HEIGHT=512
            ;;
        720p)
            WIDTH=1280
            HEIGHT=704
            ;;
        1080p)
            WIDTH=1920
            HEIGHT=1088
            ;;
        custom)
            fail "--quality custom requires --width and --height"
            ;;
        *)
            fail "--quality must be draft, 720p, 1080p, or custom"
            ;;
    esac
fi

[[ "$WIDTH" =~ ^[0-9]+$ && "$HEIGHT" =~ ^[0-9]+$ ]] || fail "width and height must be positive integers"
((WIDTH > 0 && HEIGHT > 0)) || fail "width and height must be positive"

if [[ "$QUALITY" == "custom" ]]; then
    if ((WIDTH >= HEIGHT)); then
        ORIENTATION="landscape"
    else
        ORIENTATION="portrait"
    fi
elif [[ "$ORIENTATION" == "portrait" && "$WIDTH" -gt "$HEIGHT" ]]; then
    temporary_dimension="$WIDTH"
    WIDTH="$HEIGHT"
    HEIGHT="$temporary_dimension"
elif [[ "$ORIENTATION" == "landscape" && "$HEIGHT" -gt "$WIDTH" ]]; then
    temporary_dimension="$WIDTH"
    WIDTH="$HEIGHT"
    HEIGHT="$temporary_dimension"
fi

((WIDTH % 64 == 0 && HEIGHT % 64 == 0)) \
    || fail "two-stage LTX resolution must have width and height divisible by 64 (got ${WIDTH}x${HEIGHT})"

if [[ -n "$NUM_FRAMES" ]]; then
    [[ "$NUM_FRAMES" =~ ^[0-9]+$ ]] || fail "--frames must be a positive integer"
    ((NUM_FRAMES >= 1 && (NUM_FRAMES - 1) % 8 == 0)) \
        || fail "--frames must satisfy 8K+1 (examples: 49, 81, 121, 161)"
else
    is_positive_number "$DURATION" || fail "--duration must be a positive number"
    NUM_FRAMES="$({
        awk -v duration="$DURATION" -v fps="$FPS" 'BEGIN {
            target = duration * fps
            k = int(((target - 1) / 8) + 0.5)
            if (k < 0) k = 0
            print (8 * k) + 1
        }'
    })"
fi

ACTUAL_DURATION="$(awk -v frames="$NUM_FRAMES" -v fps="$FPS" 'BEGIN { printf "%.3f", (frames - 1) / fps }')"

LTX_ROOT="${LTX_ROOT_OVERRIDE:-${ONEIROI_LTX_ROOT:-/data/oneiroi/ltx-2.3}}"
LTX_REPO_DIR="${LTX_REPO_DIR_OVERRIDE:-${ONEIROI_LTX_REPO_DIR:-$LTX_ROOT/src/LTX-2}}"
CHECKPOINT_PATH="${CHECKPOINT_PATH_OVERRIDE:-${ONEIROI_LTX_CHECKPOINT:-$LTX_ROOT/models/LTX-2.3/ltx-2.3-22b-distilled-1.1.safetensors}}"
SPATIAL_UPSAMPLER_PATH="${SPATIAL_UPSAMPLER_PATH_OVERRIDE:-${ONEIROI_LTX_UPSAMPLER:-$LTX_ROOT/models/LTX-2.3/ltx-2.3-spatial-upscaler-x2-1.1.safetensors}}"
GEMMA_ROOT="${GEMMA_ROOT_OVERRIDE:-${ONEIROI_LTX_GEMMA_ROOT:-$LTX_ROOT/models/gemma-3-12b}}"

RUN_ID="ltx-$(date +%Y%m%d-%H%M%S)"
OUTPUT_PATH="${OUTPUT_PATH:-$LTX_ROOT/outputs/inference/$RUN_ID.mp4}"
LOG_PATH="${LOG_PATH:-${OUTPUT_PATH%.*}.log}"
MANIFEST_PATH="${MANIFEST_PATH:-${OUTPUT_PATH%.*}.params}"

LTX_ROOT="$(make_absolute_path "$LTX_ROOT")"
LTX_REPO_DIR="$(make_absolute_path "$LTX_REPO_DIR")"
CHECKPOINT_PATH="$(make_absolute_path "$CHECKPOINT_PATH")"
SPATIAL_UPSAMPLER_PATH="$(make_absolute_path "$SPATIAL_UPSAMPLER_PATH")"
GEMMA_ROOT="$(make_absolute_path "$GEMMA_ROOT")"
OUTPUT_PATH="$(make_absolute_path "$OUTPUT_PATH")"
LOG_PATH="$(make_absolute_path "$LOG_PATH")"
MANIFEST_PATH="$(make_absolute_path "$MANIFEST_PATH")"
if [[ -n "$FIRST_FRAME" ]]; then
    FIRST_FRAME="$(make_absolute_path "$FIRST_FRAME")"
fi
if [[ -n "$LAST_FRAME" ]]; then
    LAST_FRAME="$(make_absolute_path "$LAST_FRAME")"
fi

[[ "${OUTPUT_PATH,,}" == *.mp4 ]] || fail "--output must end in .mp4"
[[ -d "$LTX_REPO_DIR" ]] || fail "LTX repository not found: $LTX_REPO_DIR"
[[ -f "$CHECKPOINT_PATH" ]] || fail "distilled checkpoint not found: $CHECKPOINT_PATH"
[[ -f "$SPATIAL_UPSAMPLER_PATH" ]] || fail "spatial upsampler not found: $SPATIAL_UPSAMPLER_PATH"
[[ -d "$GEMMA_ROOT" ]] || fail "Gemma directory not found: $GEMMA_ROOT"
[[ -z "$FIRST_FRAME" || -f "$FIRST_FRAME" ]] || fail "first frame not found: $FIRST_FRAME"
[[ -z "$LAST_FRAME" || -f "$LAST_FRAME" ]] || fail "last frame not found: $LAST_FRAME"

if [[ -e "$OUTPUT_PATH" && "$OVERWRITE" != "1" ]]; then
    fail "output already exists: $OUTPUT_PATH (use --overwrite to replace it)"
fi

for command_name in awk date mkdir tee uv; do
    command -v "$command_name" >/dev/null 2>&1 || fail "required command is missing: $command_name"
done

detect_cuda_library_dirs
CUDA_ENV=(CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES="$GPU")
if [[ -n "$CUDA_LINK_DIR" ]]; then
    CUDA_ENV+=(LIBRARY_PATH="$CUDA_LINK_DIR${LIBRARY_PATH:+:$LIBRARY_PATH}")
fi
if [[ -n "$CUDA_RUNTIME_DIR" ]]; then
    CUDA_ENV+=(LD_LIBRARY_PATH="$CUDA_RUNTIME_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}")
fi

if [[ "$SYNC_MODE" == "always" || ("$SYNC_MODE" == "auto" && ! -x "$LTX_REPO_DIR/.venv/bin/python") ]]; then
    if ((DRY_RUN == 1)); then
        printf 'Would run: (cd %q && uv sync --frozen)\n' "$LTX_REPO_DIR"
    else
        echo "=== Sync LTX environment ==="
        (cd "$LTX_REPO_DIR" && uv sync --frozen)
    fi
elif [[ "$SYNC_MODE" == "never" && ! -x "$LTX_REPO_DIR/.venv/bin/python" && "$DRY_RUN" != "1" ]]; then
    fail "LTX environment is missing at $LTX_REPO_DIR/.venv; remove --no-sync or run uv sync --frozen"
fi

PIPELINE_ARGS=(
    python -m ltx_pipelines.distilled
    --distilled-checkpoint-path "$CHECKPOINT_PATH"
    --spatial-upsampler-path "$SPATIAL_UPSAMPLER_PATH"
    --gemma-root "$GEMMA_ROOT"
    --prompt "$PROMPT"
    --output-path "$OUTPUT_PATH"
    --seed "$SEED"
    --height "$HEIGHT"
    --width "$WIDTH"
    --num-frames "$NUM_FRAMES"
    --frame-rate "$FPS"
    --offload "$OFFLOAD"
)

if [[ "$QUANTIZATION" != "none" ]]; then
    PIPELINE_ARGS+=(--quantization "$QUANTIZATION")
fi
if [[ "$ENHANCE_PROMPT" == "1" ]]; then
    PIPELINE_ARGS+=(--enhance-prompt)
fi
if [[ -n "$FIRST_FRAME" ]]; then
    PIPELINE_ARGS+=(--image "$FIRST_FRAME" 0 "$FIRST_FRAME_STRENGTH" "$IMAGE_CRF")
fi
if [[ -n "$LAST_FRAME" ]]; then
    PIPELINE_ARGS+=(--image "$LAST_FRAME" "$((NUM_FRAMES - 1))" "$LAST_FRAME_STRENGTH" "$IMAGE_CRF")
fi
if ((${#EXTRA_ARGS[@]} > 0)); then
    PIPELINE_ARGS+=("${EXTRA_ARGS[@]}")
fi

UV_COMMAND=(uv run --no-sync "${PIPELINE_ARGS[@]}")

printf '%s\n' \
    "=== LTX-2.3 inference ===" \
    "GPU:          $GPU" \
    "Quality:      $QUALITY ($WIDTH x $HEIGHT, $ORIENTATION)" \
    "Frames/FPS:   $NUM_FRAMES @ $FPS (${ACTUAL_DURATION}s)" \
    "First frame:  ${FIRST_FRAME:-disabled}" \
    "Last frame:   ${LAST_FRAME:-disabled}" \
    "Quantization: $QUANTIZATION" \
    "Offload:      $OFFLOAD" \
    "CUDA link:    ${CUDA_LINK_DIR:-not detected}" \
    "Output:       $OUTPUT_PATH" \
    "Log:          $LOG_PATH" \
    "Manifest:     $MANIFEST_PATH"

printf 'Command: '
printf '%q ' env "${CUDA_ENV[@]}" "${UV_COMMAND[@]}"
printf '\n'

if ((DRY_RUN == 1)); then
    echo "Dry run complete."
    exit 0
fi

mkdir -p "$(dirname -- "$OUTPUT_PATH")" "$(dirname -- "$LOG_PATH")" "$(dirname -- "$MANIFEST_PATH")"

{
    printf 'run_id=%q\n' "$RUN_ID"
    printf 'created_at=%q\n' "$(date -Is)"
    printf 'gpu=%q\n' "$GPU"
    printf 'quality=%q\n' "$QUALITY"
    printf 'orientation=%q\n' "$ORIENTATION"
    printf 'width=%q\nheight=%q\n' "$WIDTH" "$HEIGHT"
    printf 'fps=%q\nnum_frames=%q\nrequested_duration=%q\nactual_duration=%q\n' \
        "$FPS" "$NUM_FRAMES" "$DURATION" "$ACTUAL_DURATION"
    printf 'seed=%q\n' "$SEED"
    printf 'prompt=%q\n' "$PROMPT"
    printf 'first_frame=%q\nlast_frame=%q\n' "$FIRST_FRAME" "$LAST_FRAME"
    printf 'first_frame_strength=%q\nlast_frame_strength=%q\nimage_crf=%q\n' \
        "$FIRST_FRAME_STRENGTH" "$LAST_FRAME_STRENGTH" "$IMAGE_CRF"
    printf 'quantization=%q\noffload=%q\nenhance_prompt=%q\n' "$QUANTIZATION" "$OFFLOAD" "$ENHANCE_PROMPT"
    printf 'ltx_root=%q\nltx_repo_dir=%q\n' "$LTX_ROOT" "$LTX_REPO_DIR"
    printf 'checkpoint=%q\nspatial_upsampler=%q\ngemma_root=%q\n' \
        "$CHECKPOINT_PATH" "$SPATIAL_UPSAMPLER_PATH" "$GEMMA_ROOT"
    printf 'output_path=%q\nlog_path=%q\n' "$OUTPUT_PATH" "$LOG_PATH"
    printf 'command='
    printf '%q ' env "${CUDA_ENV[@]}" "${UV_COMMAND[@]}"
    printf '\n'
} >"$MANIFEST_PATH"

set +e
(
    cd "$LTX_REPO_DIR"
    for env_assignment in "${CUDA_ENV[@]}"; do
        export "$env_assignment"
    done
    if [[ -x /usr/bin/time ]]; then
        /usr/bin/time -v "${UV_COMMAND[@]}"
    else
        "${UV_COMMAND[@]}"
    fi
) 2>&1 | tee "$LOG_PATH"
run_rc=${PIPESTATUS[0]}
set -e

printf 'finished_at=%q\nexit_code=%q\n' "$(date -Is)" "$run_rc" >>"$MANIFEST_PATH"

if ((run_rc != 0)); then
    fail "inference failed with exit code $run_rc; see $LOG_PATH"
fi

[[ -s "$OUTPUT_PATH" ]] || fail "inference exited successfully but output is missing or empty: $OUTPUT_PATH"

echo "Inference completed: $OUTPUT_PATH"
