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
BROWSER_SITE_DIR="${REPO_ROOT}/demo/agent_web_browser_site"

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

# The demo HOCONs default to `claude-haiku`, which needs langchain-anthropic.
# neuro-san's base requirements only pull in langchain-openai. Auto-install
# the provider package the demo needs if it isn't there yet, so a fresh
# checkout works without manual setup.  Switch to gpt-4o-mini in the HOCONs
# if you'd rather not pull in another provider package.
ensure_anthropic_provider() {
    if "${PYTHON}" -c "import langchain_anthropic" >/dev/null 2>&1; then
        return 0
    fi
    echo "demo needs langchain-anthropic (the HOCONs use claude-haiku); installing..."
    "${PYTHON}" -m pip install --quiet 'langchain-anthropic>=1.0,<2.0' || {
        echo "" >&2
        echo "error: pip install langchain-anthropic failed." >&2
        echo "If you don't have an Anthropic key, switch the demo to OpenAI:" >&2
        echo "  sed -i.bak 's/\"claude-haiku\"/\"gpt-4o-mini\"/' \\" >&2
        echo "    demo/agent_web/{flights,hotels,travelgenius}/registries/*.hocon" >&2
        echo "  rm demo/agent_web/*/registries/*.bak" >&2
        exit 1
    }
}
ensure_anthropic_provider

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
    #
    # AGENT_LANDING_ENABLE + AGENT_STATIC_DIR turn each origin into its own
    # web "homepage": visiting http://localhost:<port>/ shows a landing page
    # listing this origin's distributable networks and embeds the chat UI
    # directly. Eliminates the need for a separate static-file server.
    PYTHONPATH="${origin_dir}:${REPO_ROOT}${PYTHONPATH:+:${PYTHONPATH}}" \
    AGENT_MANIFEST_FILE="${origin_dir}/registries/manifest.hocon" \
    AGENT_TOOL_PATH="${origin_dir}/coded_tools" \
    AGENT_HTTP_PORT="${port}" \
    AGENT_HTTP_SERVER_INSTANCES=1 \
    AGENT_ALLOW_CORS_HEADERS=1 \
    AGENT_MCP_ENABLE=false \
    AGENT_LANDING_ENABLE=1 \
    AGENT_STATIC_DIR="${BROWSER_SITE_DIR}" \
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
echo "All origins ready. Browse to any of them:"
echo "  open http://localhost:8801/    (flights.example landing page)"
echo "  open http://localhost:8802/    (hotels.example  landing page)"
echo "  open http://localhost:8803/    (travelgenius   landing page)"
echo ""
echo "Each landing page lists that origin's distributable networks and"
echo "embeds the chat UI inline. Set your LLM key once via the ⚙ button."
echo ""
echo "Headless variants:"
echo "  curl -s http://localhost:8801/api/v1/flight_finder/network | head"
echo "  ${PYTHON} -m neuro_san.client.agent_web_browser \\"
echo "      --url http://localhost:8803/api/v1/trip_planner/network \\"
echo "      --message 'SFO to Tokyo around 2026-06-14 for 7 nights, hotel near Shinjuku under \$300/night with a gym.' \\"
echo "      --sly-data passenger_email=bob@example.com \\"
echo "      --no-interactive"
