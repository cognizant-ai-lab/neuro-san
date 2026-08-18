#!/bin/bash
  
# Script set the ollama model by performing a pull command. It is expected that Ollama Service is running!

# Ollama model used by the smoke tests.
# Must match the model_name in neuro_san/registries/music_nerd_pro_llm_ollama.hocon
OLLAMA_MODEL="gemma4:e4b"

# Wait for Ollama service to become responsive
for i in {1..10}; do
  echo "Checking if Ollama API is ready..."
  curl --fail --silent http://ollama:11434/api/tags && break
  echo "Waiting 5s..."
  sleep 5
done

# Pull the Ollama model
curl http://ollama:11434/api/pull \
  -d "{ \"name\": \"${OLLAMA_MODEL}\" }"

# Wait for Ollama port to be ready (post-pull)
for i in {1..60}; do
  echo "Checking if Ollama API is ready..."
  curl --fail --silent http://ollama:11434/api/tags && break
  echo "Waiting 5s..."
  sleep 5
done

# Generate text as ollama with retry (every 30s up to 3m)
SUCCESS=0
for i in $(seq 1 6); do
  echo "⏳ Attempt #$i: Generating text…"
  if curl --fail --silent http://ollama:11434/api/generate \
        -X POST \
        -H "Content-Type: application/json" \
        -d "{
          \"model\": \"${OLLAMA_MODEL}\",
          \"prompt\": \"Briefly define reinforcement learning.\",
          \"stream\": false
        }"; then
    echo "✅ Generation succeeded on attempt #$i"
    SUCCESS=1
    break
  fi
  echo "⏱  Waiting 30s before retry…"
  sleep 30
done
if [ "$SUCCESS" -ne 1 ]; then
  echo "❌ Timeout: failed to generate after 3 minutes"
  exit 1
fi
