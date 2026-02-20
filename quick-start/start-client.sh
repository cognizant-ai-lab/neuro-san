#!/bin/bash

# Neuro SAN Client quick start Script for macOS/Linux
# This script starts the Neuro SAN CLI client

set -e

echo "==============================================="
echo "  Neuro SAN Client quick start"
echo "==============================================="
echo ""

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Activate virtual environment
if [ -d ".venv" ]; then
    VENV_DIR=".venv"
elif [ -d "venv" ]; then
    VENV_DIR="venv"
else
    echo "❌ Virtual environment not found!"
    echo "Please run start-server.sh first to set up the environment."
    exit 1
fi

echo "Activating virtual environment..."
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
echo "✅ Virtual environment activated"
echo ""

# Set PYTHONPATH
export PYTHONPATH="$PROJECT_DIR"

# Get agent name from command line argument or use default
AGENT_NAME="${1:-hello_world}"

# Check if connecting to server or running direct
if [ "$2" = "--server" ] || [ "$2" = "--http" ]; then
    echo "Connecting to server mode..."
    echo "Make sure the server is running (start-server.sh)"
    echo ""
    python -m neuro_san.client.agent_cli --http --agent "$AGENT_NAME"
else
    echo "Running in direct mode (no server)..."
    echo ""
    python -m neuro_san.client.agent_cli --agent "$AGENT_NAME"
fi
