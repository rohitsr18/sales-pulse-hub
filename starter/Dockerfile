FROM python:3.11-slim AS base
WORKDIR /app
RUN pip install --no-cache-dir --upgrade pip

FROM base AS deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM base AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LOG_LEVEL=info

COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY . .

RUN touch submission.jsonl
RUN addgroup --system hubuser && adduser --system --ingroup hubuser hubuser
RUN chown hubuser:hubuser submission.jsonl
USER hubuser

EXPOSE 3000

HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:3000/health')" || exit 1

CMD ["python", "server.py"]
