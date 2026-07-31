#!/usr/bin/env bash
# Bootstrap the official LTX-2 repository and the complete LTX-2.3
# Distilled quick-start model set documented in LTX-2/README.md.
#
# Intentionally downloaded:
#   - ltx-2.3-22b-distilled-1.1.safetensors
#   - ltx-2.3-spatial-upscaler-x2-1.1.safetensors
#   - every asset in google/gemma-3-12b-it-qat-q4_0-unquantized
#
# Intentionally excluded from the first-run baseline:
#   - Dev/HQ checkpoint
#   - x1.5 and temporal upscalers
#   - distilled and IC/control LoRAs
#   - training artifacts

set -Eeuo pipefail
umask 022

readonly REPO_URL="https://github.com/Lightricks/LTX-2.git"
readonly LTX_MODEL_REPO="Lightricks/LTX-2.3"
readonly GEMMA_MODEL_REPO="google/gemma-3-12b-it-qat-q4_0-unquantized"
readonly DISTILLED_CHECKPOINT="ltx-2.3-22b-distilled-1.1.safetensors"
readonly SPATIAL_UPSCALER="ltx-2.3-spatial-upscaler-x2-1.1.safetensors"
readonly MIN_FREE_GIB=150

LTX_ROOT="${LTX_ROOT:-/data/oneiroi/ltx-2.3}"
REPO_DIR="$LTX_ROOT/src/LTX-2"
LTX_MODEL_DIR="$LTX_ROOT/models/LTX-2.3"
GEMMA_MODEL_DIR="$LTX_ROOT/models/gemma-3-12b"
HF_HOME="${HF_HOME:-$LTX_ROOT/cache/huggingface}"
export HF_HOME
export PYTHONUNBUFFERED=1
export HF_HUB_DOWNLOAD_TIMEOUT="${HF_HUB_DOWNLOAD_TIMEOUT:-120}"

LICENSES_ACCEPTED=0

usage() {
    cat <<EOF
Usage:
  $0 --accept-model-licenses

The required flag confirms that the operator has reviewed and accepted the
terms for both gated model repositories:
  https://huggingface.co/Lightricks/LTX-2.3
  https://huggingface.co/google/gemma-3-12b-it-qat-q4_0-unquantized

Optional environment variables:
  LTX_ROOT=/data/oneiroi/ltx-2.3
  HF_HOME=/data/oneiroi/ltx-2.3/cache/huggingface
  HF_HUB_DOWNLOAD_TIMEOUT=120
EOF
}

while (($#)); do
    case "$1" in
        --accept-model-licenses)
            LICENSES_ACCEPTED=1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
    shift
done

if ((LICENSES_ACCEPTED != 1)); then
    echo "ERROR: model-license confirmation is required." >&2
    usage >&2
    exit 2
fi

mkdir -p \
    "$LTX_ROOT/src" \
    "$LTX_MODEL_DIR" \
    "$GEMMA_MODEL_DIR" \
    "$HF_HOME" \
    "$LTX_ROOT/inputs" \
    "$LTX_ROOT/outputs/smoke" \
    "$LTX_ROOT/outputs/benchmarks" \
    "$LTX_ROOT/logs" \
    "$LTX_ROOT/manifests"

RUN_ID="bootstrap-$(date +%Y%m%d-%H%M%S)"
LOG_PATH="$LTX_ROOT/logs/$RUN_ID.log"
exec > >(tee -a "$LOG_PATH") 2>&1

on_exit() {
    local rc=$?
    if ((rc == 0)); then
        echo "[$(date -Is)] Bootstrap completed successfully."
    else
        echo "[$(date -Is)] Bootstrap failed with exit code $rc. See: $LOG_PATH" >&2
    fi
}
trap on_exit EXIT

fail() {
    echo "ERROR: $*" >&2
    exit 1
}

for command_name in git hf sha256sum find sort xargs df awk tee; do
    command -v "$command_name" >/dev/null 2>&1 \
        || fail "Required command is missing: $command_name"
done

if command -v flock >/dev/null 2>&1; then
    exec 9>"$LTX_ROOT/.bootstrap.lock"
    flock -n 9 || fail "Another bootstrap process is already using $LTX_ROOT"
fi

if [[ "$(id -u)" == "0" ]]; then
    echo "WARNING: running as root. The deployment plan recommends a dedicated non-root inference user."
fi

echo "=== Environment ==="
date -Is
hostname
id
command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L || true
git --version
hf --help >/dev/null
printf 'LTX_ROOT=%s\nHF_HOME=%s\n' "$LTX_ROOT" "$HF_HOME"
df -hT "$LTX_ROOT"

available_kib="$(df -Pk "$LTX_ROOT" | awk 'NR == 2 {print $4}')"
required_kib=$((MIN_FREE_GIB * 1024 * 1024))
[[ "$available_kib" =~ ^[0-9]+$ ]] || fail "Could not determine free disk space"
if ((available_kib < required_kib)); then
    fail "Less than ${MIN_FREE_GIB} GiB is free on the filesystem containing $LTX_ROOT"
fi

echo
echo "=== Clone or verify LTX-2 ==="
if [[ -d "$REPO_DIR/.git" ]]; then
    existing_origin="$(git -C "$REPO_DIR" remote get-url origin)"
    case "$existing_origin" in
        "$REPO_URL"|git@github.com:Lightricks/LTX-2.git)
            echo "Repository already exists; preserving its current checkout."
            ;;
        *)
            fail "$REPO_DIR has an unexpected origin: $existing_origin"
            ;;
    esac
elif [[ -e "$REPO_DIR" ]]; then
    fail "$REPO_DIR exists but is not a Git repository"
else
    git clone --branch main --single-branch "$REPO_URL" "$REPO_DIR"
fi

LTX_GIT_COMMIT="$(git -C "$REPO_DIR" rev-parse HEAD)"
printf '%s\n' "$LTX_GIT_COMMIT" \
    | tee "$LTX_ROOT/manifests/ltx2-git-commit.txt"
git -C "$REPO_DIR" status --short --branch

echo
echo "=== Verify README requirements at commit $LTX_GIT_COMMIT ==="
README_PATH="$REPO_DIR/README.md"
[[ -f "$README_PATH" ]] || fail "README not found: $README_PATH"
for required_reference in \
    "$DISTILLED_CHECKPOINT" \
    "$SPATIAL_UPSCALER" \
    "$GEMMA_MODEL_REPO"; do
    grep -Fq "$required_reference" "$README_PATH" \
        || fail "Current README does not reference required asset: $required_reference"
done

grep -nEi -C 5 \
    'hf download|distilled|spatial-upscaler|gemma-3-12b' \
    "$README_PATH" \
    | tee "$LTX_ROOT/logs/$RUN_ID-readme-download-instructions.txt" || true

echo
echo "=== Hugging Face authentication ==="
if ! hf auth whoami; then
    if [[ -t 0 ]]; then
        echo "No Hugging Face login was found under HF_HOME=$HF_HOME."
        echo "Enter a Read token when prompted. The token will not be written to this script or its manifest."
        hf auth login
    else
        fail "Hugging Face login is required. Run 'HF_HOME=$HF_HOME hf auth login' interactively, then rerun."
    fi
fi

resolve_hf_revision() {
    local repo_id="$1"
    local probe_file="$2"
    local output
    local probe_path
    local revision

    echo "Resolving immutable revision for $repo_id using $probe_file ..." >&2
    if ! output="$(hf download "$repo_id" "$probe_file")"; then
        echo >&2
        echo "Access failed for $repo_id." >&2
        echo "Confirm that its model terms are accepted and the token can read gated repositories." >&2
        return 1
    fi

    printf '%s\n' "$output" >&2
    # huggingface_hub CLI output differs by version. Older releases print a
    # bare path, while 1.25+ prints a two-line status followed by
    # "path: /absolute/file". Accept both formats.
    probe_path="$(
        printf '%s\n' "$output" | awk '
            /^[[:space:]]*path:[[:space:]]*\// {
                sub(/^[[:space:]]*path:[[:space:]]*/, "")
                path = $0
                next
            }
            /^\// { path = $0 }
            END { print path }
        '
    )"
    [[ -n "$probe_path" && -f "$probe_path" ]] || {
        echo "Could not identify downloaded probe path for $repo_id from output:" >&2
        printf '%s\n' "$output" >&2
        return 1
    }

    case "$probe_path" in
        */snapshots/*/*)
            revision="${probe_path#*/snapshots/}"
            revision="${revision%%/*}"
            ;;
        *)
            echo "Could not extract an immutable revision from: $probe_path" >&2
            return 1
            ;;
    esac

    [[ "$revision" =~ ^[0-9a-f]{40}$ ]] || {
        echo "Unexpected Hugging Face revision for $repo_id: $revision" >&2
        return 1
    }

    printf '%s\n' "$revision"
}

LTX_MODEL_REVISION="$(resolve_hf_revision "$LTX_MODEL_REPO" README.md)" \
    || fail "Unable to resolve $LTX_MODEL_REPO revision"
GEMMA_MODEL_REVISION="$(resolve_hf_revision "$GEMMA_MODEL_REPO" README.md)" \
    || fail "Unable to resolve $GEMMA_MODEL_REPO revision"

echo
echo "=== Fixed model revisions ==="
printf 'LTX-2.3: %s\nGemma 3:  %s\n' \
    "$LTX_MODEL_REVISION" \
    "$GEMMA_MODEL_REVISION"

cat >"$LTX_ROOT/manifests/model-revisions.txt" <<EOF
recorded_at=$(date -Is)
license_terms_confirmed_by_operator=true
ltx_code_repository=$REPO_URL
ltx_code_commit=$LTX_GIT_COMMIT
ltx_model_repository=$LTX_MODEL_REPO
ltx_model_revision=$LTX_MODEL_REVISION
gemma_model_repository=$GEMMA_MODEL_REPO
gemma_model_revision=$GEMMA_MODEL_REVISION
EOF

echo
echo "=== Download LTX-2.3 Distilled quick-start assets ==="
hf download "$LTX_MODEL_REPO" \
    README.md \
    "$DISTILLED_CHECKPOINT" \
    "$SPATIAL_UPSCALER" \
    --revision "$LTX_MODEL_REVISION" \
    --local-dir "$LTX_MODEL_DIR"

echo
echo "=== Download all Gemma text-encoder assets ==="
hf download "$GEMMA_MODEL_REPO" \
    --revision "$GEMMA_MODEL_REVISION" \
    --local-dir "$GEMMA_MODEL_DIR"

validate_large_file() {
    local path="$1"
    local minimum_bytes="$2"
    local actual_bytes

    [[ -f "$path" ]] || fail "Required file is missing: $path"
    actual_bytes="$(stat -c '%s' "$path")"
    ((actual_bytes >= minimum_bytes)) \
        || fail "File is unexpectedly small ($actual_bytes bytes): $path"

    if head -c 256 "$path" | grep -aq 'version https://git-lfs.github.com/spec/v1'; then
        fail "File is a Git LFS pointer rather than model data: $path"
    fi
}

echo
echo "=== Validate downloaded assets ==="
validate_large_file "$LTX_MODEL_DIR/$DISTILLED_CHECKPOINT" 1000000000
validate_large_file "$LTX_MODEL_DIR/$SPATIAL_UPSCALER" 50000000

mapfile -d '' GEMMA_WEIGHT_FILES < <(
    find "$GEMMA_MODEL_DIR" -type f \
        \( -name '*.safetensors' -o -name '*.gguf' -o -name '*.bin' \) \
        -size +100M -print0
)
((${#GEMMA_WEIGHT_FILES[@]} > 0)) \
    || fail "No large Gemma weight file was found in $GEMMA_MODEL_DIR"

ensure_model_link() {
    local target="$1"
    local link_path="$2"
    local current_target

    mkdir -p "$(dirname "$link_path")"
    if [[ -L "$link_path" ]]; then
        current_target="$(readlink -f "$link_path")"
        [[ "$current_target" == "$(readlink -f "$target")" ]] \
            || fail "Existing symlink points elsewhere: $link_path -> $current_target"
    elif [[ -e "$link_path" ]]; then
        fail "Cannot create README-compatible model link because this path exists: $link_path"
    else
        ln -s "$target" "$link_path"
    fi
}

echo
echo "=== Create README-compatible model paths ==="
ensure_model_link "$LTX_MODEL_DIR" "$REPO_DIR/models/ltx-2.3"
ensure_model_link "$GEMMA_MODEL_DIR" "$REPO_DIR/models/gemma-3-12b"
ls -ld "$REPO_DIR/models/ltx-2.3" "$REPO_DIR/models/gemma-3-12b"

echo
echo "=== Write SHA256 manifest ==="
find "$LTX_MODEL_DIR" "$GEMMA_MODEL_DIR" \
    -type f \
    -not -path '*/.cache/*' \
    -print0 \
    | sort -z \
    | xargs -0 sha256sum \
    | tee "$LTX_ROOT/manifests/model-sha256.txt"

echo
echo "=== Final summary ==="
du -sh "$REPO_DIR" "$LTX_MODEL_DIR" "$GEMMA_MODEL_DIR" "$HF_HOME" 2>/dev/null || true
df -hT "$LTX_ROOT"
cat "$LTX_ROOT/manifests/model-revisions.txt"

cat <<EOF

Ready.
Repository:         $REPO_DIR
LTX checkpoint:     $LTX_MODEL_DIR/$DISTILLED_CHECKPOINT
Spatial upscaler:   $LTX_MODEL_DIR/$SPATIAL_UPSCALER
Gemma text encoder: $GEMMA_MODEL_DIR
Log:                $LOG_PATH

README-compatible paths were linked under:
  $REPO_DIR/models/ltx-2.3
  $REPO_DIR/models/gemma-3-12b
EOF
