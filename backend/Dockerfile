FROM python:3.11-slim

WORKDIR /app

# Set environment variables for browsers
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/app/ms-playwright

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libpq-dev gcc curl wget gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (for faster rebuilds)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers and their system dependencies
RUN playwright install --with-deps chromium

# Copy application code
COPY . .

# Create logs directory
RUN mkdir -p /app/logs

# Expose port
EXPOSE 5000

# Run with gunicorn
# Use 1 worker for browser automation on small instances to avoid memory issues
# Timeout increased to 180s for browser rendering
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--timeout", "180", "app:create_app()"]
