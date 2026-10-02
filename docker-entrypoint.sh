#!/bin/sh
set -e
python manage.py migrate --noinput
python manage.py createcachetable
python manage.py seed_reference
exec "$@"
