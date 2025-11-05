# Stage 1: Builder
FROM python:3.12-slim-bookworm AS builder

WORKDIR /app

# Use a reliable mirror and retry mechanism without sed
RUN apt-get clean && rm -rf /var/lib/apt/lists/* && \
    for i in 1 2 3; do \
        apt-get update --allow-releaseinfo-change && \
        apt-get install -y --no-install-recommends \
            build-essential \
            libpq-dev \
            curl && break || sleep 5; \
    done && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --prefix=/install -r requirements.txt

# Stage 2: Final image
FROM python:3.12-slim-bookworm

WORKDIR /app

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Copy project code
COPY . .

# Ensure STATIC_ROOT directory exists
RUN mkdir -p /app/staticfiles && \
    chown -R 1000:1000 /app/staticfiles

# Create a non-root user
RUN useradd -u 1000 -ms /bin/bash appuser


# Switch to non-root user
USER appuser

# Expose port for Gunicorn
EXPOSE 8080

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV DJANGO_SETTINGS_MODULE=alx_travel_app.settings
ENV STATIC_ROOT=/app/staticfiles

# Collect static files after dependencies are in place
# Removed the RUN python manage.py collectstatic --noinput from build stage

# Gunicorn for Django with migrations and static collection at runtime
CMD ["/bin/sh", "-c", "python manage.py migrate --noinput && python manage.py collectstatic --noinput && gunicorn alx_travel_app.wsgi:application --bind 0.0.0.0:8080 --workers 2 --threads 2 --log-level info"]
