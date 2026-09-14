# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM debian:13-slim

ARG MEMORY_SYNC_UID=10000
ARG MEMORY_SYNC_GID=10000

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    HOME=/home/memory-sync

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        git \
        openssh-client \
        util-linux \
    && groupadd --gid "${MEMORY_SYNC_GID}" memory-sync \
    && useradd \
        --uid "${MEMORY_SYNC_UID}" \
        --gid "${MEMORY_SYNC_GID}" \
        --create-home \
        --shell /bin/bash \
        memory-sync \
    && rm -rf /var/lib/apt/lists/*

COPY hermes-memory-sync.sh /usr/local/bin/hermes-memory-sync
COPY entrypoint.sh /usr/local/bin/hermes-memory-sync-entrypoint
RUN chmod 0755 \
    /usr/local/bin/hermes-memory-sync \
    /usr/local/bin/hermes-memory-sync-entrypoint

USER memory-sync:memory-sync

ENTRYPOINT ["/usr/local/bin/hermes-memory-sync-entrypoint"]
