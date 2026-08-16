FROM python:3.12-slim

RUN useradd --create-home --uid 10001 appuser
WORKDIR /app

COPY requirements.txt pyproject.toml README.md /app/
COPY pjm_nowcast /app/pjm_nowcast
COPY fixtures /app/fixtures

RUN pip install --no-cache-dir -r requirements.txt \
    && mkdir -p /data \
    && chown -R appuser:appuser /app /data

USER appuser
ENV DATA_DIR=/data
ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8000'), timeout=4)"

CMD ["sh", "-c", "uvicorn pjm_nowcast.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
