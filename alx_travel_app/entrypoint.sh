#!/bin/bash
set -e

# Export port for supervisord
export ENV_PORT=${PORT:-8000}

# Start supervisord
exec supervisord -c /app/supervisord.conf
