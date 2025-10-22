FROM python:3.11-slim-bookworm

ENV LANG C.UTF-8
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install --yes --no-install-recommends alsa-utils

WORKDIR /app

COPY script/setup ./script/
COPY setup.py requirements.txt MANIFEST.in ./
COPY wyoming_mic_external/ ./wyoming_mic_external/

RUN script/setup

COPY script/run ./script/
COPY docker/run ./

EXPOSE 10600

ENTRYPOINT ["/app/run"]
