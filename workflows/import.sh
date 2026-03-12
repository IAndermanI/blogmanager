#!/bin/sh
# Import all workflows on startup
for f in /home/node/workflows/*.json; do
  echo "Importing $f..."
  n8n import:workflow --input="$f"
done

# Start n8n normally
n8n start