FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY pyproject.toml ./
COPY techflip ./techflip
RUN pip install --no-cache-dir ".[api]" \
 # bake the French postal table in, so the scanner never depends on a download at runtime
 && python -c "import pgeocode; pgeocode.Nominatim('fr')"

COPY config ./config

RUN useradd --system --uid 10001 techflip && mkdir -p /data && chown techflip /data
USER techflip
ENV TECHFLIP_DB=/data/techflip.db

CMD ["python", "-m", "techflip.cli", "serve", "8000"]
