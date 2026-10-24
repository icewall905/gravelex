FROM python:3.13-slim
ARG GRAVELEX_REF=398aed9d3687c64472c3b9302b7ffa621d581950
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/backend
ARG BUILD_VERSION=0.1.3
ARG BUILD_ARCH=amd64
LABEL io.hass.version=$BUILD_VERSION io.hass.type="app" io.hass.arch=$BUILD_ARCH
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl tar && rm -rf /var/lib/apt/lists/* && mkdir -p /tmp/gravelex-src /app/backend /app/web /app/scripts /data
RUN curl -fsSL "https://github.com/icewall905/gravelex/archive/${GRAVELEX_REF}.tar.gz" -o /tmp/gravelex.tar.gz && tar -xzf /tmp/gravelex.tar.gz -C /tmp/gravelex-src --strip-components=1 && cp -a /tmp/gravelex-src/health-hub/backend/. /app/backend/ && cp -a /tmp/gravelex-src/health-hub/web/. /app/web/ && cp -a /tmp/gravelex-src/health-hub/scripts/. /app/scripts/ && cp /tmp/gravelex-src/health-hub/requirements.txt /app/requirements.txt && rm -rf /tmp/gravelex-src /tmp/gravelex.tar.gz
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY run.py /app/run.py
ENTRYPOINT ["python", "/app/run.py"]
