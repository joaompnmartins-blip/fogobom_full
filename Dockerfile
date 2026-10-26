FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin libgdal-dev libgeos-dev libproj-dev binutils libpq-dev gcc g++ postgresql-client \
    && rm -rf /var/lib/apt/lists/*

ENV GDAL_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu/libgdal.so
ENV GEOS_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu/libgeos_c.so
ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN cd backend && SECRET_KEY=build-only-not-secret python manage.py collectstatic --noinput

EXPOSE 8000
# Pre-migration backup (skipped if BACKUP_S3_* unset; a failure never blocks the start),
# then the daily backup loop in the background and gunicorn in the foreground.
CMD ["sh", "-c", "cd backend && (python manage.py backup || echo 'Backup antes do deploy falhou') && python manage.py migrate --noinput && python manage.py ensure_superuser && (python manage.py backup_scheduler &) && exec gunicorn fire_mgmt.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 2 --timeout 120"]
