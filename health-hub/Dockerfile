FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FITNESS_DB=/data/fitness.sqlite3 WEB_DIR=/app/web DOWNLOAD_DIR=/downloads
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && mkdir -p /data /downloads && chown 10001:10001 /data /downloads
COPY backend/ ./
COPY scripts/rebuild-minutes.py scripts/set-password.py ./scripts/
COPY web/ ./web/
USER 10001:10001
EXPOSE 8790 9998
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:8790", "--access-logfile", "-", "dashboard:app"]
