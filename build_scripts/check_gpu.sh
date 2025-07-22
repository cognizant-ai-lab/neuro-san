#!/bin/bash
  
# Script check for GPU

if command -v nvidia-smi >/dev/null 2>&1; then
      echo "✅ nvidia-smi found:"
      nvidia-smi
else
  echo "⚠️  No NVIDIA GPU detected (nvidia-smi not in PATH)"
fi