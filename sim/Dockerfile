FROM python:3.11-slim AS base
WORKDIR /app

# Install pip tools, then clean cache to keep image small
RUN pip install --no-cache-dir --upgrade pip

# ── Install dependencies (production only) ──────────────────────
FROM base AS deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Final runtime image ──────────────────────────────────────────
FROM base AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LOG_LEVEL=info

COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY . .

# Drop root privileges
RUN addgroup --system simuser && adduser --system --ingroup simuser simuser
USER simuser

EXPOSE 7000 7001 7002 7003 7004 7005

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:7000/health')" || exit 1

CMD ["python", "server.py"]
