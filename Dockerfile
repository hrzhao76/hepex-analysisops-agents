FROM ghcr.io/astral-sh/uv:python3.12-bookworm

SHELL ["/bin/bash", "-lc"]

# ----------------------------
# System dependencies
# ----------------------------
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    curl \
    sudo \
    build-essential \
    cmake \
    xrootd-client \
    xrootd-server \
    python3-xrootd \
    nodejs \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Install Node.js 20
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
 && apt-get update \
 && apt-get install -y --no-install-recommends nodejs \
 && rm -rf /var/lib/apt/lists/*

# ----------------------------
# Create non-root user & grant sudo
# ----------------------------
RUN adduser --disabled-password --gecos "" agent \
 && echo "agent ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/agent \
 && chmod 0440 /etc/sudoers.d/agent
 
USER agent
WORKDIR /home/agent
ENV HOME=/home/agent

# ----------------------------
# Install analysis environment
# ----------------------------
RUN python -m venv .ana-venv \
 && source .ana-venv/bin/activate \
 && pip install xrootd atlasopenmagic uproot awkward vector matplotlib mplhep pyyaml tqdm 'pyhf[backends]' coffea\
 && python3 -c "import sys; from atlasopenmagic import install_from_environment; install_from_environment()"

# ----------------------------
# Install OpenHarness
# ----------------------------
RUN curl -fsSL https://raw.githubusercontent.com/HKUDS/OpenHarness/main/scripts/install.sh | bash -s -- --from-source --with-channels

# Monkey patch OpenHarness OpenAI client
RUN sed -i 's/"max_tokens": request.max_tokens,/"max_completion_tokens": request.max_tokens,/g' \
    /home/agent/.openharness-src/src/openharness/api/openai_client.py \
 && export PATH=/home/agent/.openharness-venv/bin:$PATH \
 && oh provider use openai-compatible

# ----------------------------
# Copy project files
# ----------------------------
COPY --chown=agent:agent pyproject.toml uv.lock README.md ./
COPY --chown=agent:agent src src
COPY --chown=agent:agent src/agent_01_oh/skills/sm-ana-aod/skills /home/agent/.openharness/skills
COPY --chown=agent:agent src/agent_01_oh/AGENTS.md AGENTS.md

# ----------------------------
# Install app dependencies with uv first
# ----------------------------
RUN --mount=type=cache,target=/home/agent/.cache/uv,uid=1000 \
    uv sync --locked

# ----------------------------
# Runtime env
# ----------------------------
ENV PATH="/home/agent/.openharness-venv/bin:/home/agent/.local/bin:$PATH"

ENTRYPOINT ["uv", "run", "src/server.py"]
CMD ["--host", "0.0.0.0"]
EXPOSE 9009
