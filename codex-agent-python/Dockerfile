FROM python:3.11-slim

WORKDIR /app

# 先复制依赖声明，利用 Docker 构建缓存。
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

# 再复制应用代码和 Agent Skill。
COPY app ./app
COPY .agents ./.agents

ENV AGENT_WORKSPACE=/app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
