# Dockerfile (place at repo root)
FROM python:3.12-slim

# system deps (adjust as needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    supervisor \
  && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy and install python deps
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy source
COPY . /app

# Supervisord config
COPY deploy/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Expose port (gunicorn will bind to 8000)
EXPOSE 8000

# Set environment (Render will override env vars)
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

# Start supervisord which in turn starts gunicorn + celery
CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/conf.d/supervisord.conf"]

