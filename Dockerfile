FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
# Faker is needed for `seed_demo`; it is small and harmless in production.
RUN pip install -r requirements-dev.txt

COPY . .
RUN DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput

RUN useradd --create-home buss && mkdir -p /app/media && chown -R buss /app/media
USER buss

EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["gunicorn", "buss.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
