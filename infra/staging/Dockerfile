FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY services/api/pyproject.toml /app/services/api/pyproject.toml
RUN pip install --no-cache-dir \
      'fastapi>=0.115,<1' \
      'pydantic>=2.7,<3' \
      'uvicorn[standard]>=0.30,<1' \
      'psycopg[binary]>=3.2,<4' \
      'boto3>=1.35,<2' \
      'redis>=5,<6'

COPY services /app/services
COPY scripts/staging/worker.py /app/scripts/staging/worker.py
COPY scripts/staging/api_entrypoint.py /app/scripts/staging/api_entrypoint.py
COPY scripts/staging/s3_init.py /app/scripts/staging/s3_init.py

FROM runtime AS api
EXPOSE 8000
CMD ["uvicorn", "scripts.staging.api_entrypoint:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS worker
EXPOSE 8081
CMD ["python", "scripts/staging/worker.py"]

FROM runtime AS s3-init
CMD ["python", "scripts/staging/s3_init.py"]
