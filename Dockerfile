# syntax=docker/dockerfile:1

# ---- Stage 1: build the headless Linux RakSAMP client ----
FROM debian:bookworm-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends \
        g++ cmake make ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY rakfk/ ./rakfk/
RUN cmake -S rakfk -B /build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build /build -j"$(nproc)" \
    && mkdir -p /opt/rakb/bin \
    && cp /build/bin/raksamp /opt/rakb/bin/raksamp

# ---- Stage 2: Python Telegram supervisor ----
FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/app/data \
    RAKSAMP_BIN=/opt/rakb/bin/raksamp \
    PORT=8080
# Code lives in /opt/rakb, NOT /app: BotHost bind-mounts /app from Git at runtime,
# which would hide anything the image placed there. /app/data is the persistent volume.
WORKDIR /opt/rakb
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY tgbot/ ./tgbot/
COPY --from=build /opt/rakb/bin/raksamp /opt/rakb/bin/raksamp
EXPOSE 8080
CMD ["python", "-m", "tgbot"]
