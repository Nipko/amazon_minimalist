#!/bin/sh
# Startup script: initializes data directory on first run

DATA_DIR="/app/data"

# Create subdirectories
mkdir -p "$DATA_DIR/public"

# Copy default config if not present (first deploy with empty volume)
if [ ! -f "$DATA_DIR/apartments.json" ]; then
    echo "First run: copying default apartments.json to data volume..."
    cp /app/defaults/apartments.json "$DATA_DIR/apartments.json"
fi

if [ ! -f "$DATA_DIR/blocks.json" ]; then
    echo "First run: creating empty blocks.json..."
    echo "{}" > "$DATA_DIR/blocks.json"
fi

# Start the API server
exec uvicorn api:app --host 0.0.0.0 --port 8000
