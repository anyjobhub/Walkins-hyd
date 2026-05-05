FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for psycopg2 and browser automation
RUN apt-get update && apt-get install -y \
    libpq-dev gcc curl \
    wget gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install Playwright and its system dependencies
RUN pip install playwright
RUN playwright install chromium
RUN playwright install-deps chromium


# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create logs directory
RUN mkdir -p /app/logs

# Expose port
EXPOSE 5000

# Run with gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "--timeout", "120", "app:create_app()"]
