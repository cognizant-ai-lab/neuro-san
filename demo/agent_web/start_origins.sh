#!/usr/bin/env bash
#
# Start the three demo Agent Web origins for the trip-planner demo.
#
#   flights.example      -> localhost:8801
#   hotels.example       -> localhost:8802
#   travelgenius.example -> localhost:8803
#
# Each is a standalone neuro-san server with its own manifest + coded_tools.
# Logs go to /tmp/agent_web_demo_<origin>.log.
#
# Stop all three with:  ./stop_origins.sh

set -euo pipefail

DEMO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${DEMO_ROOT}/../.." && pwd)"

# Pick the Python that has neuro-san installed.
PYTHON="${PYTHON:-${REPO_ROOT}/.venv/bin/python}"
if [[ ! -x "${PYTHON}" ]]; then
    PYTHON="$(command -v python3 || true)"
fi
if [[ -z "${PYTHON}" ]]; then
    echo "error: no python interpreter found" >&2
    exit 1
fi

mkdir -p /tmp

start_origin() {
    local origin_name="$1"
    local port="$2"
    local origin_dir="${DEMO_ROOT}/${origin_name}"
    local log_file="/tmp/agent_web_demo_${origin_name}.log"
    local pid_file="/tmp/agent_web_demo_${origin_name}.pid"

    if [[ -f "${pid_file}" ]] && kill -0 "$(cat "${pid_file}")" 2>/dev/null; then
        echo "Origin ${origin_name} is already running (pid $(cat "${pid_file}")). Stop it first."
        return 0
    fi

    # PYTHONPATH must include the origin dir so the `coded_tools` package under
    # it is importable. We also prepend REPO_ROOT so neuro_san is found when
    # the venv is not present.
    PYTHONPATH="${origin_dir}:${REPO_ROOT}${PYTHONPATH:+:${PYTHONPATH}}" \
    AGENT_MANIFEST_FILE="${origin_dir}/registries/manifest.hocon" \
    AGENT_TOOL_PATH="${origin_dir}/coded_tools" \
    AGENT_HTTP_PORT="${port}" \
    AGENT_HTTP_SERVER_INSTANCES=1 \
    AGENT_ALLOW_CORS_HEADERS=1 \
    AGENT_MCP_ENABLE=false \
        nohup "${PYTHON}" -m neuro_san.service.main_loop.server_main_loop \
        > "${log_file}" 2>&1 &
    local pid=$!
    echo "${pid}" > "${pid_file}"
    echo "  ${origin_name} -> http://localhost:${port} (pid ${pid}, log ${log_file})"
}

echo "Starting Agent Web demo origins..."
start_origin "flights" 8801
start_origin "hotels" 8802
start_origin "travelgenius" 8803

echo ""
echo "Waiting for origins to come up..."
for port in 8801 8802 8803; do
    for _ in $(seq 1 30); do
        if curl --silent --fail "http://localhost:${port}/readyz" > /dev/null 2>&1; then
            echo "  localhost:${port} ready"
            break
        fi
        sleep 0.5
    done
done

echo ""
echo "All origins ready. Try:"
echo "  curl -s http://localhost:8801/api/v1/flight_finder/network | head"
echo "  ${PYTHON} -m neuro_san.client.agent_web_browser \\"
echo "      --url http://localhost:8803/api/v1/trip_planner/network \\"
echo "      --message 'SFO to Tokyo around 2026-06-14 for 7 nights, hotel near Shinjuku under \$300/night with a gym.' \\"
echo "      --sly-data passenger_email=bob@example.com \\"
echo "      --no-interactive"
