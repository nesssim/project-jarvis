FROM python:3.12-slim AS builder
WORKDIR /app
COPY shared/ /app/shared/
COPY services/orchestrator/pyproject.toml /app/services/orchestrator/
RUN pip install --no-cache-dir /app/shared/

FROM python:3.12-slim AS runtime
RUN addgroup --system --gid 1001 app && adduser --system --uid 1001 app
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY services/orchestrator/src/ /app/src/
COPY shared/src/ /app/shared_src/
ENV PYTHONPATH=/app/src:/app/shared_src
USER app
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "orchestrator.main:app", "--host", "0.0.0.0", "--port", "8000"]
