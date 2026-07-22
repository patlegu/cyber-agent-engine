# syntax=docker/dockerfile:1
# Image bi-rôle (serveur d'agents OU coordinateur) — CPU, non-root.
# La commande réelle est fournie par docker-compose. GPU : override documenté.

FROM python:3.11-slim AS builder
WORKDIR /build
COPY pyproject.toml MANIFEST.in README.md ./
COPY core ./core
COPY coordinator ./coordinator
COPY agents ./agents
COPY clients ./clients
COPY server.py ./
RUN pip install --no-cache-dir --upgrade "setuptools>=77" wheel \
    && pip install --no-cache-dir --prefix=/install .

FROM python:3.11-slim AS runtime
# utilisateur non-root
RUN useradd --create-home --uid 10001 appuser
COPY --from=builder /install /usr/local
WORKDIR /app
COPY server.py ./
COPY dashboard ./dashboard
RUN mkdir -p /data && chown appuser:appuser /data
USER appuser
# CMD par défaut = coordinateur ; compose surcharge par service.
CMD ["cyber-coordinator"]
