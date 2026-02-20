#!/bin/bash

# Neuro-SAN Server Startup Script for macOS/Linux
# This script handles all necessary steps to launch the neuro-san server

set -e

echo "==============================================="
echo "  Neuro-SAN Server Startup"
echo "==============================================="
echo ""

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "Project directory: $PROJECT_DIR"
echo ""

# Check if virtual environment exists and recreate if needed
if [ -d ".venv" ] || [ -d "venv" ]; then
    echo "Existing virtual environment found, removing to avoid outdated dependencies..."
    rm -rf .venv venv
fi

echo "Creating virtual environment..."
python3 -m venv .venv
echo "✅ Virtual environment created"
echo ""

# Activate virtual environment
VENV_DIR=".venv"

echo "Activating virtual environment..."
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
echo "✅ Virtual environment activated"
echo ""

# Set PYTHONPATH
export PYTHONPATH="$PROJECT_DIR"
echo "PYTHONPATH set to: $PYTHONPATH"
echo ""

# Check if dependencies are installed
echo "Checking dependencies..."
if ! python -c "import neuro_san" 2>/dev/null; then
    echo "Installing dependencies..."
    pip install -r requirements.txt
    echo "✅ Dependencies installed"
else
    echo "✅ Dependencies already installed"
fi
echo ""

# Enable CORS headers for web applications
export AGENT_ALLOW_CORS_HEADERS=1
echo "✅ CORS headers enabled"
echo ""

# Check if port is already in use
PORT=${AGENT_HTTP_PORT:-8080}
if lsof -Pi :"$PORT" -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo "❌ ERROR: Port $PORT is already in use!"
    echo ""
    echo "To see what's using the port:"
    echo "  lsof -i :$PORT"
    echo ""
    echo "To stop the process using the port:"
    echo "  kill \$(lsof -t -i :$PORT)"
    echo ""
    exit 1
fi

# Start the server
echo "==============================================="
echo "  Starting Neuro SAN Server on port $PORT"
echo "==============================================="
echo ""
echo "Server will be available at: http://localhost:$PORT"
echo "Press Ctrl+C to stop the server"
echo ""

python -m neuro_san.service.main_loop.server_main_loop
