FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir httpx apscheduler pyyaml

COPY ops_reporter.py .
COPY claws_runner.py .
COPY .env .
COPY config/ config/
COPY CLAWS.md TASTE.md SOUL.md ./

RUN mkdir -p memory/raw memory/filtered memory/deep-dives memory/reflections memory/reviews memory/feedback logs

HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
  CMD python -c "import os; assert os.path.exists('logs/claws.log'), 'No log file'" || exit 1

ENTRYPOINT ["python", "-u", "claws_runner.py"]
