#!/bin/bash
  
# Script check available memory

# Grab available memory in kB
AVAILABLE_KB=$(grep MemAvailable /proc/meminfo | awk '{print $2}')
echo "🖥️  ${AVAILABLE_KB} kB available"

# Convert kB → GB (1 GB = 1024 × 1024 kB) to two decimal places
AVAILABLE_GB=$(awk "BEGIN { printf \"%.2f\", ${AVAILABLE_KB} / (1024*1024) }")
echo "🖥️  ${AVAILABLE_GB} GB available"

# Threshold: fail if under 1 GB
THRESHOLD_KB=$((1 * 1024 * 1024))
if [ "${AVAILABLE_KB}" -lt "${THRESHOLD_KB}" ]; then
  echo "::error ::Not enough memory (only ${AVAILABLE_GB} GB available)"
  exit 1
fi