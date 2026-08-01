#!/usr/bin/env bash
set -Eeuo pipefail

BASE_URL="${ONEIROI_PRIVATE_API_BASE_URL:-http://127.0.0.1:18000}"
OWNER="${ONEIROI_PRIVATE_API_OWNER:-private-api-smoke}"
RUN_GPU="${ONEIROI_PRIVATE_API_GPU:-0}"
FIRST_FRAME="${ONEIROI_PRIVATE_API_FIRST_FRAME:-}"
TIMEOUT_SECONDS="${ONEIROI_PRIVATE_API_TIMEOUT_SECONDS:-1800}"
PYTHON_BIN="${ONEIROI_PRIVATE_API_PYTHON:-python3}"
COOKIE="oneiroi_user=$OWNER"
SESSION_ID=""
TMP_DIR="$(mktemp -d)"

cleanup() {
    local code=$?
    if [[ -n "$SESSION_ID" ]]; then
        curl --noproxy '*' -sS \
            -H "Cookie: $COOKIE" \
            -H 'Content-Type: application/json' \
            -X POST \
            -d '{"policy":"when_idle","confirmed":false}' \
            "$BASE_URL/v1/compute/sessions/$SESSION_ID/release" >/dev/null || true
    fi
    rm -rf "$TMP_DIR"
    exit "$code"
}
trap cleanup EXIT INT TERM

request() {
    curl --noproxy '*' --fail-with-body -sS -H "Cookie: $COOKIE" "$@"
}

json_field() {
    local expression="$1"
    "$PYTHON_BIN" -c 'import json,sys
value=json.load(sys.stdin)
for part in sys.argv[1].split("."):
    value=value[int(part)] if isinstance(value,list) else value[part]
print(value)' "$expression"
}

assert_json() {
    local expression="$1"
    local expected="$2"
    "$PYTHON_BIN" -c 'import json,sys
value=json.load(sys.stdin)
for part in sys.argv[1].split("."):
    value=value[int(part)] if isinstance(value,list) else value[part]
expected=sys.argv[2]
actual=str(value).lower() if isinstance(value,bool) else str(value)
assert actual == expected, f"{sys.argv[1]}: expected {expected!r}, got {actual!r}"' \
        "$expression" "$expected"
}

printf 'GET /healthz\n'
request "$BASE_URL/healthz" | assert_json service bff

printf 'GET /v1/compute/capabilities\n'
request "$BASE_URL/v1/compute/capabilities" | "$PYTHON_BIN" -c 'import json,sys
value=json.load(sys.stdin)
assert value["requestedDefault"] == 4
assert value["maximumSelectable"] == 4
assert {item["tier"] for item in value["profiles"]} == {"fast", "hq"}'

printf 'POST /v1/conversations\n'
CREATE_RESPONSE="$(request \
    -H 'Content-Type: application/json' \
    -X POST \
    -d '{"title":"Private API smoke"}' \
    "$BASE_URL/v1/conversations")"
CONVERSATION_ID="$(printf '%s' "$CREATE_RESPONSE" | json_field id)"
[[ "$CONVERSATION_ID" == conversation-* ]]

printf 'PUT /v1/conversations/%s (twice)\n' "$CONVERSATION_ID"
for _ in 1 2; do
    request \
        -H 'Content-Type: application/json' \
        -X PUT \
        -d '{"title":"Private API smoke updated"}' \
        "$BASE_URL/v1/conversations/$CONVERSATION_ID" \
        | "$PYTHON_BIN" -c 'import json,sys
value=json.load(sys.stdin)
assert value["id"] == sys.argv[1]
assert value["title"] == "Private API smoke updated"' "$CONVERSATION_ID"
done

printf 'GET conversation detail/list and PUT negative cases\n'
request "$BASE_URL/v1/conversations/$CONVERSATION_ID" \
    | assert_json title 'Private API smoke updated'
request "$BASE_URL/v1/conversations" | "$PYTHON_BIN" -c 'import json,sys
items=json.load(sys.stdin)
conversation_id=sys.argv[1]
assert sum(item["id"] == conversation_id for item in items) == 1' "$CONVERSATION_ID"

WRONG_STATUS="$(curl --noproxy '*' -sS -o /dev/null -w '%{http_code}' \
    -H 'Cookie: oneiroi_user=private-api-other' \
    "$BASE_URL/v1/conversations/$CONVERSATION_ID")"
[[ "$WRONG_STATUS" == 404 ]]
INVALID_STATUS="$(curl --noproxy '*' -sS -o /dev/null -w '%{http_code}' \
    -H "Cookie: $COOKIE" \
    -H 'Content-Type: application/json' \
    -X PUT -d '{"title":""}' \
    "$BASE_URL/v1/conversations/$CONVERSATION_ID")"
[[ "$INVALID_STATUS" == 422 ]]

if [[ "$RUN_GPU" != 1 ]]; then
    printf 'PASS non-GPU GET/POST/PUT loopback chain\n'
    exit 0
fi

[[ -n "$FIRST_FRAME" && -f "$FIRST_FRAME" ]] || {
    printf 'ONEIROI_PRIVATE_API_FIRST_FRAME must name an existing image\n' >&2
    exit 2
}

printf 'GET /v1/compute/gpus\n'
INVENTORY="$(request "$BASE_URL/v1/compute/gpus")"
printf '%s' "$INVENTORY" | "$PYTHON_BIN" -c 'import json,sys
value=json.load(sys.stdin)
assert value["requestedDefault"] == 4
assert value["maximumSelectable"] == 4
eligible=[gpu for gpu in value["gpus"] if gpu["eligible"]]
assert eligible, "no eligible GPU"
assert all(gpu["id"].startswith("GPU-") for gpu in value["gpus"])
assert all(not gpu["eligible"] for gpu in value["gpus"] if gpu["state"] == "foreign_busy")'

printf 'POST one-card compute session\n'
SESSION_RESPONSE="$(request \
    -H 'Content-Type: application/json' \
    -H "Idempotency-Key: private-api-$CONVERSATION_ID" \
    -X POST \
    -d '{"requestedGpuCount":1,"selectionMode":"auto","gpuIds":[],"profilePolicy":"balanced","allowPartial":true}' \
    "$BASE_URL/v1/compute/sessions")"
SESSION_ID="$(printf '%s' "$SESSION_RESPONSE" | json_field id)"
printf '%s' "$SESSION_RESPONSE" | "$PYTHON_BIN" -c 'import json,sys
value=json.load(sys.stdin)
assert value["allocatedGpuCount"] == 1
assert value["profilePlan"] == {"fast": 1, "hq": 0}
assert value["state"] in {"ready", "degraded"}
assert value["slots"][0]["profile"] == "fast"
assert value["slots"][0]["state"] == "ready"'

printf 'GET compute snapshot and SSE replay\n'
request "$BASE_URL/v1/compute/sessions/$SESSION_ID" | assert_json slots.0.state ready
set +e
request --max-time 5 "$BASE_URL/v1/compute/sessions/$SESSION_ID/events" \
    >"$TMP_DIR/compute-events.txt"
SSE_STATUS=$?
set -e
[[ "$SSE_STATUS" == 0 || "$SSE_STATUS" == 28 ]]
grep -q 'event: compute.session.ready' "$TMP_DIR/compute-events.txt"

printf 'GET one-card capabilities (HQ hard-disabled)\n'
request "$BASE_URL/v1/compute/capabilities?sessionId=$SESSION_ID" | "$PYTHON_BIN" -c 'import json,sys
value=json.load(sys.stdin)
fast=next(item for item in value["profiles"] if item["tier"] == "fast")
hq=next(item for item in value["profiles"] if item["tier"] == "hq")
assert fast["available"] is True
assert hq["available"] is False
assert hq["unavailableReason"] == "HQ_REQUIRES_AT_LEAST_2_GPUS"'

printf 'POST multipart image upload\n'
UPLOAD_RESPONSE="$(request \
    -X POST \
    -F "file=@$FIRST_FRAME" \
    -F 'title=Private API first frame' \
    "$BASE_URL/v1/uploads/images")"
ASSET_ID="$(printf '%s' "$UPLOAD_RESPONSE" | json_field id)"

printf 'POST real Fast I2V job\n'
JOB_PAYLOAD="$("$PYTHON_BIN" -c 'import json,sys
print(json.dumps({
  "conversationId": sys.argv[1],
  "computeSessionId": sys.argv[2],
  "draft": {
    "prompt": "A locked-off cinematic shot with subtle natural motion, stable lighting and consistent identity.",
    "negativePrompt": "camera shake, identity change, text, watermark",
    "queue": "fast",
    "profile": "fast",
    "ratio": "16:9",
    "resolution": "720p",
    "duration": 5,
    "seed": 42,
    "firstFrameAssetId": sys.argv[3],
    "firstStrength": 1.0,
    "lastStrength": 1.0,
    "enhancePrompt": False,
    "quantization": "fp8-cast",
    "offload": "none"
  }
}))' "$CONVERSATION_ID" "$SESSION_ID" "$ASSET_ID")"
JOB_RESPONSE="$(request \
    -H 'Content-Type: application/json' \
    -X POST \
    -d "$JOB_PAYLOAD" \
    "$BASE_URL/v1/jobs/i2v")"
JOB_ID="$(printf '%s' "$JOB_RESPONSE" | json_field id)"

request --max-time "$TIMEOUT_SECONDS" "$BASE_URL/v1/jobs/$JOB_ID/events" \
    >"$TMP_DIR/job-events.txt" &
SSE_PID=$!
DEADLINE=$((SECONDS + TIMEOUT_SECONDS))
while (( SECONDS < DEADLINE )); do
    SNAPSHOT="$(request "$BASE_URL/v1/jobs/$JOB_ID")"
    STAGE="$(printf '%s' "$SNAPSHOT" | json_field stage)"
    case "$STAGE" in
        succeeded) break ;;
        failed|cancelled)
            printf 'Job terminal failure: %s\n' "$STAGE" >&2
            printf '%s\n' "$SNAPSHOT" >&2
            exit 1
            ;;
    esac
    sleep 2
done
[[ "$STAGE" == succeeded ]]
wait "$SSE_PID"
grep -q 'event: job.succeeded' "$TMP_DIR/job-events.txt"

printf 'GET job file and manifest\n'
request "$BASE_URL/v1/jobs/$JOB_ID/file" >"$TMP_DIR/result.mp4"
request "$BASE_URL/v1/jobs/$JOB_ID/manifest" >"$TMP_DIR/manifest.json"
"$PYTHON_BIN" -c 'import json,sys
value=json.load(open(sys.argv[1], encoding="utf-8"))
assert value["jobId"] == sys.argv[2]
assert "path" not in json.dumps(value).lower()' "$TMP_DIR/manifest.json" "$JOB_ID"
ffprobe -v error -show_entries format=format_name,duration,size \
    -of default=noprint_wrappers=1 "$TMP_DIR/result.mp4" \
    >"$TMP_DIR/ffprobe.txt"
grep -q 'format_name=.*mp4' "$TMP_DIR/ffprobe.txt"

printf 'POST release and verify terminal snapshot\n'
RELEASE_RESPONSE="$(request \
    -H 'Content-Type: application/json' \
    -X POST \
    -d '{"policy":"when_idle","confirmed":false}' \
    "$BASE_URL/v1/compute/sessions/$SESSION_ID/release")"
printf '%s' "$RELEASE_RESPONSE" | assert_json state released
RELEASED_SESSION_ID="$SESSION_ID"
SESSION_ID=""

printf 'PASS full private API chain conversation=%s session=%s job=%s\n' \
    "${CONVERSATION_ID:0:25}" "${RELEASED_SESSION_ID:0:24}" "${JOB_ID:0:24}"
cat "$TMP_DIR/ffprobe.txt"
