#!/usr/bin/env bash
#
# Stop the three demo Agent Web origins (started by start_origins.sh).

set -u

for origin in flights hotels travelgenius; do
    pid_file="/tmp/agent_web_demo_${origin}.pid"
    if [[ -f "${pid_file}" ]]; then
        pid="$(cat "${pid_file}")"
        if kill "${pid}" 2>/dev/null; then
            echo "Stopped ${origin} (pid ${pid})"
        fi
        rm -f "${pid_file}"
    fi
done
