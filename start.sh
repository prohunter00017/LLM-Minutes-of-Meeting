#!/bin/bash
set -e

# Start Celery worker (background)
celery -A celery_worker:celery worker -l info -c 4 &

# Start Celery beat scheduler (background)
celery -A celery_worker:celery beat -l info &

# Start Flask web server (foreground — Railway healthchecks this process)
exec python run.py