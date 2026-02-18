FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Store defaults so they can be copied to empty volume on first run
RUN mkdir -p /app/defaults && \
    cp /app/data/apartments.json /app/defaults/ && \
    cp /app/data/apartments_details.json /app/defaults/

# Create data directories
RUN mkdir -p /app/data/public

# Make startup script executable
RUN chmod +x /app/start.sh

# Expose the API port
EXPOSE 8000

# Use startup script that initializes data volume
CMD ["/app/start.sh"]
