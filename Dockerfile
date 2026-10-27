FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends iproute2 iputils-ping samba-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY helix_it ./helix_it
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir "ldap3>=2.9" "pywinrm>=0.4" "smbprotocol>=1.13"

ENV PYTHONPATH=/app \
    HELIX_DATA=/data \
    HELIX_BIND=0.0.0.0 \
    HELIX_PORT=8080 \
    PYTHONDONTWRITEBYTECODE=1

VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('HELIX_PORT','8080'), timeout=4).read()"

CMD ["python", "-m", "helix_it.web"]
