#!/usr/bin/env bash
set -euo pipefail

# One container runs the whole app: Gunicorn for the web app, plus the durable
# background worker and the retention cleanup loop as separate processes
# (outside Gunicorn, so a web-worker restart never loses accepted work).
# Set START_EMBEDDED_WORKER=0 or START_EMBEDDED_CLEANUP=0 only when that
# process is supervised elsewhere against the same database and uploads.

export FLASK_APP="${FLASK_APP:-app}"
export PATH="/app/.local/bin:${PATH}"

if [[ "${SKIP_BOOTSTRAP:-0}" != "1" ]]; then
  echo ">>> Running application bootstrap..."
  flask bootstrap
else
  echo ">>> SKIP_BOOTSTRAP is set. Skipping bootstrap step."
fi

gunicorn_command=(/app/.local/bin/gunicorn \
  --bind "0.0.0.0:5004" \
  --workers "${GUNICORN_WORKERS:-4}" \
  --timeout "${GUNICORN_TIMEOUT:-120}" \
  --graceful-timeout "${GUNICORN_GRACEFUL_TIMEOUT:-1800}" \
  --max-requests "${GUNICORN_MAX_REQUESTS:-0}" \
  --max-requests-jitter "${GUNICORN_MAX_REQUESTS_JITTER:-0}" \
  --forwarded-allow-ips "${GUNICORN_FORWARDED_ALLOW_IPS:-*}" \
  --log-level "${GUNICORN_LOG_LEVEL:-info}" \
  "app:create_app()")

pids=()

if [[ "${START_EMBEDDED_WORKER:-1}" == "1" ]]; then
  echo ">>> Starting background worker..."
  /app/.local/bin/flask worker &
  pids+=("$!")
fi

if [[ "${START_EMBEDDED_CLEANUP:-1}" == "1" ]]; then
  echo ">>> Starting retention cleanup loop..."
  /app/.local/bin/flask cleanup-loop &
  pids+=("$!")
fi

if [[ ${#pids[@]} -eq 0 ]]; then
  echo ">>> Starting Gunicorn..."
  exec "${gunicorn_command[@]}"
fi

echo ">>> Starting Gunicorn..."
"${gunicorn_command[@]}" &
pids+=("$!")

stop_children() {
  trap - TERM INT
  kill -TERM "${pids[@]}" 2>/dev/null || true
  wait "${pids[@]}" 2>/dev/null || true
}

# If any process exits, stop the others and exit so the container restarts.
trap 'stop_children; exit 143' TERM INT
status=0
wait -n "${pids[@]}" || status=$?
stop_children
exit "$status"
