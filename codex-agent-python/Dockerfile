FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    AGENT_WORKSPACE=/app

WORKDIR /app

# 先安装依赖，便于 Docker 层缓存；Runtime 依赖的 Codex CLI 由 openai-codex 包配套安装。
COPY pyproject.toml ./
COPY app ./app
COPY .agents ./.agents
COPY migrations ./migrations
RUN pip install .

# Runtime 不以 root 身份运行。Codex 的认证/状态目录应在部署环境中以持久卷或受控 Secret 提供。
RUN useradd --create-home --uid 10001 agent \
    && chown -R agent:agent /app
USER agent

EXPOSE 8000

# 容器内只运行一个应用进程，水平扩容交给 Kubernetes/ECS 等编排层。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
