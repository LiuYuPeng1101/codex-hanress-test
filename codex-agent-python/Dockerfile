FROM python:3.11-slim

WORKDIR /app

# 复制 Python 项目源码和依赖声明。
# 第一版优先保证结构清晰和可构建，后续再做多阶段构建和依赖缓存优化。
COPY pyproject.toml ./
COPY app ./app
COPY .agents ./.agents

RUN pip install --no-cache-dir .

# Codex Thread 的 cwd 会指向 /app，因此可以发现 /app/.agents/skills。
ENV AGENT_WORKSPACE=/app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
