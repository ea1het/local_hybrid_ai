FROM debian:13-slim

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        inotify-tools \
        python3 \
    && rm -rf /var/lib/apt/lists/*

COPY cleanup.py /usr/local/bin/hermes-sandbox-cleanup
RUN chmod 0755 /usr/local/bin/hermes-sandbox-cleanup

ENTRYPOINT ["/usr/local/bin/hermes-sandbox-cleanup"]
