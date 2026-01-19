#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

usage() {
  cat <<'EOF'
Usage:
  services/data-pipeline/infra/loadtest/run.sh --env <staging|production> --scenario <ramp|sustained|spike> [options]

Options:
  --config <path>         Use an explicit config file (default: config/<env>.json)
  --base-url <url>        Override config.base_url
  --out-dir <path>        Override output directory
  --allow-production      Required when --env production
  --dry-run               Print resolved command and exit
EOF
}

ENV_NAME="staging"
SCENARIO="ramp"
ALLOW_PRODUCTION="0"
CONFIG_PATH=""
BASE_URL_OVERRIDE=""
OUT_DIR=""
DRY_RUN="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)
      ENV_NAME="${2:-}"
      shift 2
      ;;
    --scenario)
      SCENARIO="${2:-}"
      shift 2
      ;;
    --config)
      CONFIG_PATH="${2:-}"
      shift 2
      ;;
    --base-url)
      BASE_URL_OVERRIDE="${2:-}"
      shift 2
      ;;
    --out-dir)
      OUT_DIR="${2:-}"
      shift 2
      ;;
    --allow-production)
      ALLOW_PRODUCTION="1"
      shift 1
      ;;
    --dry-run)
      DRY_RUN="1"
      shift 1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$CONFIG_PATH" ]]; then
  CONFIG_PATH="config/${ENV_NAME}.json"
fi

if [[ "$ENV_NAME" == "production" && "$ALLOW_PRODUCTION" != "1" ]]; then
  echo "Refusing to run against production without --allow-production" >&2
  exit 2
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found" >&2
  exit 2
fi
if ! command -v k6 >/dev/null 2>&1; then
  echo "k6 not found. Install: https://k6.io/docs/get-started/installation/" >&2
  exit 2
fi

CONFIG_ABS="$(python3 - "$CONFIG_PATH" <<'PY'
from pathlib import Path
import sys

print(Path(sys.argv[1]).expanduser().resolve())
PY
)"

BASE_URL="$(python3 - "$CONFIG_ABS" <<'PY'
import json
import sys
from pathlib import Path

cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(cfg.get("base_url") or "")
PY
)"

if [[ -n "$BASE_URL_OVERRIDE" ]]; then
  BASE_URL="$BASE_URL_OVERRIDE"
fi

if [[ -z "$BASE_URL" ]]; then
  echo "base_url is empty. Set it in $CONFIG_ABS or use --base-url" >&2
  exit 2
fi

if [[ "$BASE_URL" != http://* && "$BASE_URL" != https://* ]]; then
  echo "base_url must start with http:// or https://, got: $BASE_URL" >&2
  exit 2
fi

RUN_ID="$(python3 - <<'PY'
import datetime as dt
print(dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
PY
)"

if [[ -z "$OUT_DIR" ]]; then
  OUT_DIR="results/${ENV_NAME}/${RUN_ID}-${SCENARIO}"
fi

OUT_DIR_ABS="$(python3 - "$OUT_DIR" <<'PY'
from pathlib import Path
import sys

print(Path(sys.argv[1]).expanduser().resolve())
PY
)"

mkdir -p "$OUT_DIR_ABS"
cp "$CONFIG_ABS" "$OUT_DIR_ABS/config.json"

SUMMARY_PATH="$OUT_DIR_ABS/summary.json"

K6_CMD=(k6 run -e "CONFIG=$CONFIG_ABS" -e "BASE_URL=$BASE_URL" -e "SCENARIO=$SCENARIO" --summary-export "$SUMMARY_PATH" "k6/tiles.js")

if [[ "$DRY_RUN" == "1" ]]; then
  printf '%q ' "${K6_CMD[@]}"
  echo
  exit 0
fi

"${K6_CMD[@]}"

python3 "report/generate_report.py" \
  --summary "$SUMMARY_PATH" \
  --config "$CONFIG_ABS" \
  --scenario "$SCENARIO" \
  --out-dir "$OUT_DIR_ABS" \
  --run-id "$RUN_ID"

echo "Report: $OUT_DIR_ABS/report.html"
