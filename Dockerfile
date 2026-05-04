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
# Create non-root user
# ----------------------------
RUN adduser --disabled-password --gecos "" agent
USER agent
WORKDIR /home/agent
ENV HOME=/home/agent

# ----------------------------
# Install OpenHarness
# ----------------------------
WORKDIR /home/agent
RUN curl -fsSL https://raw.githubusercontent.com/HKUDS/OpenHarness/main/scripts/install.sh | bash -s -- --from-source --with-channels

# Monkey patch OpenHarness OpenAI client
RUN sed -i 's/"max_tokens": request.max_tokens,/"max_completion_tokens": request.max_tokens,/g' \
    /home/agent/.openharness-src/src/openharness/api/openai_client.py \
 && export PATH=/home/agent/.openharness-venv/bin:$PATH \
 && oh provider use openai-compatible

# Keep the image default aligned with the benchmark report. Runtime requests
# still override this through OPENHARNESS_MODEL when solver_model is provided.
RUN python -c "import json, pathlib; p=pathlib.Path('/home/agent/.openharness/settings.json'); d=json.loads(p.read_text()); d['model']='gpt-5'; prof=d.get('profiles',{}).get('openai-compatible',{}); prof.update({'default_model':'gpt-5','last_model':'gpt-5'}); p.write_text(json.dumps(d, indent=2)+'\n')"

# ----------------------------
# Copy project files
# ----------------------------
COPY --chown=agent:agent pyproject.toml uv.lock README.md ./
COPY --chown=agent:agent src src
COPY --chown=agent:agent src/agent_01_oh/skills/sm-ana-aod /home/agent/.openharness/skills
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
