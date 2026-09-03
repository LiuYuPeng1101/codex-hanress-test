FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    AGENT_WORKSPACE=/app \
    CODEX_HOME=/var/lib/codex

WORKDIR /app

# Codex CLI 由 openai-codex 包配套安装。
COPY pyproject.toml ./
COPY app ./app
COPY .agents ./.agents
COPY migrations ./migrations
RUN pip install .

# 单 Agent Service 仍使用非 root 用户；CODEX_HOME 挂持久卷用于 Thread resume。
RUN useradd --create-home --uid 10001 agent \
    && mkdir -p /var/lib/codex \
    && chown -R agent:agent /app /var/lib/codex
USER agent

VOLUME ["/var/lib/codex"]
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
