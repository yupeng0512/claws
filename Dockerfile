FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ops_reporter.py .
COPY claws_runner.py .
COPY api_server.py .
COPY pipeline_state.py .
COPY memory_store.py .
# config/ and dashboard/ are also volume-mounted in docker-compose.yml.
# These COPYs provide fallbacks so the image works standalone without mounts.
COPY config/ config/
COPY dashboard/ dashboard/
COPY CLAWS.md TASTE.md SOUL.md ./

RUN mkdir -p memory/raw memory/filtered memory/deep-dives memory/reflections memory/reviews memory/feedback memory/state logs

HEALTHCHECK --interval=120s --timeout=10s --retries=3 \
  CMD python -c "from pathlib import Path; p=Path('logs/claws.log'); assert p.exists() and p.stat().st_size > 0" || exit 1

ENTRYPOINT ["python", "-u", "claws_runner.py"]
