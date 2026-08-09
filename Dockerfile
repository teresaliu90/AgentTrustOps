FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY examples ./examples

RUN python -m pip install --upgrade pip \
    && python -m pip install '.[api,postgres,oidc]' \
    && groupadd --system agenttrustops \
    && useradd --system --gid agenttrustops --home-dir /app agenttrustops \
    && mkdir -p /data \
    && chown -R agenttrustops:agenttrustops /app /data \
    && chmod 600 /app/examples/api-identities.example.json

USER agenttrustops

EXPOSE 8787
VOLUME ["/data"]

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/healthz', timeout=2)"]

ENTRYPOINT ["agenttrust"]
CMD ["--help"]
