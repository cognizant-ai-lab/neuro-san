#!/bin/bash
  

if ! ps -p $(cat agent.pid) > /dev/null; then
  echo "❌ Server process failed to start"
  echo "----- agent.log -----"
  cat agent.log
  exit 1
fi

echo "✅ Server process started with PID $(cat agent.pid)"

for i in {1..30}; do
  PORT_8080_READY=false
  PORT_30011_READY=false

  if nc -z localhost 8080; then
    PORT_8080_READY=true
  fi

  if nc -z localhost 30011; then
    PORT_30011_READY=true
  fi

  if [ "$PORT_8080_READY" = true ] && [ "$PORT_30011_READY" = true ]; then
    echo "✅ Both ports are ready after awaiting $i seconds"
    break
  fi

  echo "⏳ Waiting for ports 8080 and 30011... ($i/30)"
  sleep 1
done

if ! nc -z localhost 8080 || ! nc -z localhost 30011; then
  echo "❌ Timeout: One or both ports failed to open after $i seconds"
  exit 1
fi

until curl -s http://localhost:8080/health > /dev/null; do
  echo "Waiting for server health endpoint..."
  sleep 1
done

echo "✅ Server is healthy and ready"

netstat -tuln | grep -E '8080|30011'


