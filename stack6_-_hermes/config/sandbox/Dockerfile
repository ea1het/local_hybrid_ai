FROM debian:13-slim

ARG SANDBOX_UID=1000
ARG SANDBOX_GID=1000

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:/home/agent/.local/bin:${PATH}

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        wget \
        git \
        openssh-server \
        openssh-client \
        procps \
        jq \
        file \
        ripgrep \
        less \
        nano \
        unzip \
        zip \
        tar \
        gzip \
        xz-utils \
        build-essential \
        pkg-config \
        python3 \
        python3-pip \
        python3-venv \
        nodejs \
        npm \
        pandoc \
        poppler-utils \
        ghostscript \
        libreoffice-core \
        libreoffice-writer \
        libreoffice-calc \
        libreoffice-impress \
    && python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip wheel setuptools \
    && /opt/venv/bin/pip install --no-cache-dir \
        requests \
        beautifulsoup4 \
        markdown \
        pypdf \
        python-docx \
        openpyxl \
        xlsxwriter \
        python-pptx \
        pandas \
        pytest \
        ruff \
        uv \
    && groupadd --gid "${SANDBOX_GID}" agent \
    && useradd \
        --uid "${SANDBOX_UID}" \
        --gid "${SANDBOX_GID}" \
        --create-home \
        --shell /bin/bash \
        agent \
    && mkdir -p /workspace /run/sshd /home/agent/.ssh \
    && chown -R agent:agent /workspace /home/agent \
    && chmod 0700 /home/agent/.ssh \
    && printf '%s\n' \
        'Port 2222' \
        'Protocol 2' \
        'HostKey /etc/ssh/hostkeys/ssh_host_ed25519_key' \
        'PermitRootLogin no' \
        'PasswordAuthentication no' \
        'KbdInteractiveAuthentication no' \
        'PubkeyAuthentication yes' \
        'AuthorizedKeysFile .ssh/authorized_keys' \
        'AllowUsers agent' \
        'AllowAgentForwarding no' \
        'AllowTcpForwarding no' \
        'GatewayPorts no' \
        'X11Forwarding no' \
        'PermitTunnel no' \
        'PermitUserEnvironment no' \
        'ClientAliveInterval 120' \
        'ClientAliveCountMax 2' \
        > /etc/ssh/sshd_config.d/hermes-sandbox.conf \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /usr/local/bin/hermes-sandbox-entrypoint
RUN chmod 0755 /usr/local/bin/hermes-sandbox-entrypoint

WORKDIR /workspace
EXPOSE 2222

ENTRYPOINT ["/usr/local/bin/hermes-sandbox-entrypoint"]
CMD ["/usr/sbin/sshd", "-D", "-e"]

