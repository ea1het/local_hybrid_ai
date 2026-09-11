FROM rust:1.95.0-bookworm AS builder

ARG BUZZ_SOURCE_REPOSITORY=https://github.com/block/buzz.git
ARG BUZZ_SOURCE_REF

RUN test -n "${BUZZ_SOURCE_REF}"
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates pkg-config libssl-dev clang cmake \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
RUN git clone --filter=blob:none "${BUZZ_SOURCE_REPOSITORY}" buzz \
    && cd buzz \
    && git fetch --depth 1 origin "${BUZZ_SOURCE_REF}" \
    && git checkout --detach FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = "${BUZZ_SOURCE_REF}"

WORKDIR /src/buzz
RUN cargo build --locked --release -p buzz-cli

FROM debian:bookworm-slim AS artifact
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /src/buzz/target/release/buzz /usr/local/bin/buzz
RUN test -x /usr/local/bin/buzz
CMD ["/bin/true"]
