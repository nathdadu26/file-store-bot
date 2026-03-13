FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies needed by cloudscraper
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all bot files
COPY filestorebot.py .
COPY health_check.py .

# Expose health check port
EXPOSE 8000

# Run the bot
CMD ["python", "filestorebot.py"]
