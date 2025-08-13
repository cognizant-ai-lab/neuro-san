#!/bin/bash

# Copyright (C) 2023-2025 Cognizant Digital Business, Evolutionary AI.
# All Rights Reserved.
# Issued under the Academic Public License.
#
# You can be released from the terms, and requirements of the Academic Public
# License by purchasing a commercial license.
# Purchase of a commercial license is mandatory for any use of the
# neuro-san SDK Software in commercial settings.
#
# END COPYRIGHT

set -e

REQUIRED_GO_VERSION="1.23"
OPEN_API_PLUGIN="protoc-gen-openapi-enums"

echo "🔍 Checking for ${OPEN_API_PLUGIN} in PATH..."

if command -v ${OPEN_API_PLUGIN} >/dev/null 2>&1 && [ -x "$(command -v ${OPEN_API_PLUGIN})" ]; then
  echo "✅ Found ${OPEN_API_PLUGIN} at: $(command -v ${OPEN_API_PLUGIN})"
  exit 0
fi

echo "❌ ${OPEN_API_PLUGIN} not found in PATH or not executable."
echo ""
echo "📋 To install it, follow these steps:"

OS=$(uname)

if [[ "$OS" == "Darwin" ]]; then
  echo ""
  echo "🛠 macOS Installation:"
  echo "1. Install Go (version >= $REQUIRED_GO_VERSION):"
  echo "   brew install go"
  echo ""
  echo "2. Install protoc-gen-openapi plug-in from kollalabs git repo:"
  echo "   go install github.com/kollalabs/protoc-gen-openapi@latest"
  echo ""
  echo "3. Rename this executable to the proper name:"
  echo "   mv ${HOME}/go/bin/protoc-gen-openapi ${HOME}/go/bin/${OPEN_API_PLUGIN}"
  echo ""
  echo "4. Add to PATH:"
  echo "   export PATH=\"\$PATH:\$HOME/go/bin\""
elif [[ "$OS" == "Linux" ]]; then
  echo ""
  echo "🛠 Linux Installation:"
  echo "1. Install Go (version >= $REQUIRED_GO_VERSION):"
  echo "   Visit https://go.dev/dl/ and download the latest Go tarball"
  echo "   Example:"
  echo "   wget https://go.dev/dl/go1.23.0.linux-amd64.tar.gz"
  echo "   sudo rm -rf /usr/local/go"
  echo "   sudo tar -C /usr/local -xzf go1.23.0.linux-amd64.tar.gz"
  echo "   export PATH=\"\$PATH:/usr/local/go/bin\""
  echo ""
  echo "2. Install protoc-gen-openapi plug-in from kollalabs git repo:"
  echo "   go install github.com/kollalabs/protoc-gen-openapi@latest"
  echo ""
  echo "3. Rename this executable to the proper name:"
  echo "   mv ${HOME}/go/bin/protoc-gen-openapi ${HOME}/go/bin/${OPEN_API_PLUGIN}"
  echo ""
  echo "4. Add to PATH:"
  echo "   export PATH=\"\$PATH:\$HOME/go/bin\""
else
  echo "⚠️ Unsupported OS: $OS"
fi

exit 1
