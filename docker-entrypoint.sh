#!/bin/sh
set -e
python manage.py migrate --noinput
python manage.py createcachetable
python manage.py seed_reference
# Test environment: fill an empty database with fake demo data (does nothing when students exist).
if [ "$DEMO_MODE" = "1" ]; then
    python manage.py seed_demo
fi
exec "$@"
