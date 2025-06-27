#!/usr/bin/env bash

# set -euo pipefail

pymarkdown --config ./.pymarkdownlint.yaml scan ./docs ./README.md
