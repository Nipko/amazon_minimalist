#!/bin/sh
# Startup script: initializes data directory on first run

DATA_DIR="/app/data"

# Create subdirectories
mkdir -p "$DATA_DIR/public"

# Copy default configs if not present (first deploy with empty volume)
if [ ! -f "$DATA_DIR/apartments.json" ]; then
    echo "First run: copying default apartments.json to data volume..."
    cp /app/defaults/apartments.json "$DATA_DIR/apartments.json"
fi

if [ ! -f "$DATA_DIR/apartments_details.json" ]; then
    echo "First run: copying default apartments_details.json to data volume..."
    cp /app/defaults/apartments_details.json "$DATA_DIR/apartments_details.json"
fi

if [ ! -f "$DATA_DIR/blocks.json" ]; then
    echo "First run: creating empty blocks.json..."
    echo "{}" > "$DATA_DIR/blocks.json"
fi

# Always update apartments_details.json with latest version from image
echo "Updating apartments_details.json..."
cp /app/defaults/apartments_details.json "$DATA_DIR/apartments_details.json"

# Start the API server
exec uvicorn api:app --host 0.0.0.0 --port 8000
