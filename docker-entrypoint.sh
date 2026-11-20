#!/usr/bin/env bash
set -euo pipefail

# One container runs the whole app: Gunicorn for the web app, plus the durable
# background worker as a separate process (outside Gunicorn, so a web-worker
# restart never loses accepted work). Retention cleanup runs as a thread
# inside the worker process.
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
start_worker="${START_EMBEDDED_WORKER:-1}"
start_cleanup="${START_EMBEDDED_CLEANUP:-1}"

if [[ "$start_worker" == "1" && "$start_cleanup" == "1" ]]; then
  # Cleanup works for about a second every six hours, so it runs as a thread
  # of the worker instead of costing a whole Python process.
  echo ">>> Starting background worker with retention cleanup..."
  /app/.local/bin/flask worker --with-cleanup &
  pids+=("$!")
elif [[ "$start_worker" == "1" ]]; then
  echo ">>> Starting background worker..."
  /app/.local/bin/flask worker &
  pids+=("$!")
elif [[ "$start_cleanup" == "1" ]]; then
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
