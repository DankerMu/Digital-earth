#!/bin/sh
set -e

SCRIPT_NAME="10-inject-config"

TEMPLATE_PATH="/usr/share/nginx/html/config.template.json"
OUTPUT_PATH="/usr/share/nginx/html/config.json"

log() {
  echo "[$SCRIPT_NAME] $*" >&2
}

validate_token() {
  token="${DIGITAL_EARTH_WEB_CESIUM_ION_ACCESS_TOKEN:-}"
  if [ -z "$token" ]; then
    unset DIGITAL_EARTH_WEB_CESIUM_ION_ACCESS_TOKEN
    return 0
  fi

  case "$token" in
    *[!a-zA-Z0-9._-]*)
      log "WARN: DIGITAL_EARTH_WEB_CESIUM_ION_ACCESS_TOKEN contains illegal characters; ignoring (allowed: [a-zA-Z0-9._-])"
      unset DIGITAL_EARTH_WEB_CESIUM_ION_ACCESS_TOKEN
      return 0
      ;;
  esac

  export DIGITAL_EARTH_WEB_CESIUM_ION_ACCESS_TOKEN="$token"
}

generate_config() {
  if [ ! -f "$TEMPLATE_PATH" ]; then
    log "WARN: $TEMPLATE_PATH not found; skipping config.json generation"
    return 0
  fi

  if ! command -v envsubst >/dev/null 2>&1; then
    log "WARN: envsubst not found; skipping config.json generation"
    return 0
  fi

  output_dir="${OUTPUT_PATH%/*}"
  if [ -e "$OUTPUT_PATH" ]; then
    if [ ! -w "$OUTPUT_PATH" ]; then
      log "INFO: $OUTPUT_PATH is not writable; skipping config.json generation"
      return 0
    fi
  elif [ ! -w "$output_dir" ]; then
    log "INFO: $output_dir is not writable; skipping config.json generation"
    return 0
  fi

  tmpfile="$(mktemp)"
  if ! envsubst '${DIGITAL_EARTH_WEB_CESIUM_ION_ACCESS_TOKEN}' <"$TEMPLATE_PATH" >"$tmpfile"; then
    log "WARN: envsubst failed; skipping config.json generation"
    rm -f "$tmpfile"
    return 0
  fi

  if mv "$tmpfile" "$OUTPUT_PATH" 2>/dev/null; then
    chmod 644 "$OUTPUT_PATH" 2>/dev/null || true
  else
    log "WARN: $OUTPUT_PATH is not writable; skipping config.json generation"
    rm -f "$tmpfile"
  fi
}

validate_token
generate_config
