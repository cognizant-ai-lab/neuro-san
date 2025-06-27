#!/usr/bin/env bash

# set -euo pipefail

# Only run markdown linting if `markdownlint` is installed
echo "🔍 Checking if markdownlint is installed..."
if command -v markdownlint >/dev/null 2>&1; then \
    echo "✅ markdownlint is installed."; \
    markdownlint -c .markdownlint.yaml "**/*.md" --ignore venv; \
else \
	echo "❌ markdownlint is NOT installed."; \
fi