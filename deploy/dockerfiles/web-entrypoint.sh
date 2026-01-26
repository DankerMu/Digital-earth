#!/bin/sh
set -e

TEMPLATE_PATH="/usr/share/nginx/html/config.template.json"
OUTPUT_PATH="/usr/share/nginx/html/config.json"

generate_config() {
  if [ ! -f "$TEMPLATE_PATH" ]; then
    echo "[web-entrypoint] WARN: $TEMPLATE_PATH not found; skipping config.json generation" >&2
    return 0
  fi

  if ! command -v envsubst >/dev/null 2>&1; then
    echo "[web-entrypoint] WARN: envsubst not found; skipping config.json generation" >&2
    return 0
  fi

  export DIGITAL_EARTH_WEB_CESIUM_ION_ACCESS_TOKEN="${DIGITAL_EARTH_WEB_CESIUM_ION_ACCESS_TOKEN:-}"

  tmpfile="$(mktemp)"
  if ! envsubst '${DIGITAL_EARTH_WEB_CESIUM_ION_ACCESS_TOKEN}' <"$TEMPLATE_PATH" >"$tmpfile"; then
    echo "[web-entrypoint] WARN: envsubst failed; skipping config.json generation" >&2
    rm -f "$tmpfile"
    return 0
  fi

  if mv "$tmpfile" "$OUTPUT_PATH" 2>/dev/null; then
    chmod 644 "$OUTPUT_PATH" 2>/dev/null || true
  else
    echo "[web-entrypoint] WARN: $OUTPUT_PATH is not writable; skipping config.json generation" >&2
    rm -f "$tmpfile"
  fi
}

generate_config

if [ "$#" -eq 0 ]; then
  set -- nginx -g 'daemon off;'
fi

exec "$@"
