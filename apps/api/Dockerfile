FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/api

COPY pyproject.toml ./
RUN pip install .

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

EXPOSE 8000

# Migrasi dijalankan oleh deploy/update.sh sebelum container di-restart.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
