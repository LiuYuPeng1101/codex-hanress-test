FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    AGENT_WORKSPACE=/app

WORKDIR /app

RUN groupadd --system agent && useradd --system --gid agent --home-dir /home/agent agent

COPY pyproject.toml ./
COPY app ./app
COPY .agents ./.agents

RUN pip install . \
    && chown -R agent:agent /app /home/agent

USER agent

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
