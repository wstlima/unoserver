# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice \
        libreoffice-core \
        libreoffice-writer \
        libreoffice-calc \
        libreoffice-draw \
        libreoffice-impress \
        libreoffice-base \
        python3-uno \
        fonts-dejavu \
        fonts-lato \
        locales \
        procps \
    && rm -rf /var/lib/apt/lists/*

RUN sed -i '/^# en_US.UTF-8 UTF-8/s/^# //' /etc/locale.gen \
    && locale-gen en_US.UTF-8

ENV LANG=en_US.UTF-8 \
    LC_ALL=en_US.UTF-8 \
    PYTHONPATH=/usr/lib/python3/dist-packages:$PYTHONPATH

WORKDIR /app

COPY pyproject.toml README.rst CHANGES.rst CONTRIBUTORS.rst LICENSE MANIFEST.in ./
COPY src ./src
COPY tests ./tests

RUN pip install --no-cache-dir . pytest

RUN pytest
RUN rm -rf tests

RUN useradd --create-home --home-dir /home/appuser appuser \
    && mkdir -p /var/tmp/unoserver \
    && chown -R appuser:appuser /home/appuser /var/tmp/unoserver /app

ENV PATH=/home/appuser/.local/bin:$PATH

USER appuser

EXPOSE 2003 8080

# CMD [
#     "uvicorn",
#     "unoserver.api:app",
#     "--host",
#     "0.0.0.0",
#     "--port",
#     "8080"
# ]
