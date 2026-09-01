# Codex Agent Python

这是一个标准的 FastAPI Agent Service 示例，用来演示：

> 已有 Java / Spring Boot 业务系统时，如何使用 Python + FastAPI + 官方 OpenAI Codex Python SDK 开发独立 Agent Service，再通过 HTTP / MCP 与 Java 系统集成。

## 目录结构

```text
codex-agent-python/
├── app/
│   ├── main.py                  # FastAPI 应用入口
│   ├── api/
│   │   ├── deps.py              # FastAPI Depends 依赖注入
│   │   └── v1/
│   │       ├── router.py        # V1 总路由
│   │       ├── health.py        # 健康检查
│   │       └── agent.py         # Agent HTTP API
│   ├── core/
│   │   ├── config.py            # 环境变量 / 配置
│   │   └── lifespan.py          # 应用启动与关闭生命周期
│   ├── runtime/
│   │   └── codex_runtime.py     # 官方 Codex SDK 适配层
│   ├── services/
│   │   └── agent_service.py     # Agent 应用服务
│   └── schemas/
│       └── agent.py             # Pydantic 请求 / 响应模型
├── .agents/
│   └── skills/
│       └── order-analysis/
│           └── SKILL.md
├── tests/
├── .env.example
├── pyproject.toml
├── Dockerfile
└── README.md
```

## 架构

```text
Java Business System
        |
        | HTTP
        v
FastAPI Agent Service
        |
        v
AgentService
        |
        v
CodexRuntime
        |
        v
官方 openai-codex Python SDK
        |
        v
Codex Runtime / Harness
        |
        +------ Skills
        |
        +------ MCP（下一步接 Java 业务系统）
```

## 为什么使用 AsyncCodex

FastAPI 本身是异步 Web 框架，因此这里使用官方 SDK 的 `AsyncCodex`。

FastAPI 启动时只创建一份 Codex Runtime：

```text
FastAPI startup
      |
      v
AsyncCodex start
      |
      v
整个应用生命周期复用
      |
      v
FastAPI shutdown
      |
      v
AsyncCodex close
```

不会每来一个 HTTP 请求就重新启动一份 Codex Runtime。

## Thread / Turn API

创建一个新的 Agent 聊天窗口：

```http
POST /api/v1/agents/threads
```

响应：

```json
{
  "thread_id": "thr_xxx"
}
```

在同一个 Thread 中执行一轮 Turn：

```http
POST /api/v1/agents/threads/{thread_id}/turns
Content-Type: application/json

{
  "message": "帮我分析订单1001"
}
```

响应：

```json
{
  "thread_id": "thr_xxx",
  "answer": "..."
}
```

## Skill 如何发现

环境变量：

```text
AGENT_WORKSPACE=.
```

创建 Thread 时，`CodexRuntime` 会把 workspace 作为：

```python
await codex.thread_start(cwd=str(workspace))
```

因此 Codex 可以从：

```text
<workspace>/.agents/skills
```

发现项目级 Skill。

Docker 中：

```text
AGENT_WORKSPACE=/app
```

对应：

```text
/app/.agents/skills/order-analysis/SKILL.md
```

## 本地运行

推荐 Python 3.11。

```bash
cd codex-agent-python
python -m venv .venv
```

Windows：

```bash
.venv\Scripts\activate
```

安装：

```bash
pip install -e ".[dev]"
```

复制配置：

```bash
copy .env.example .env
```

启动：

```bash
uvicorn app.main:app --reload
```

打开 Swagger：

```text
http://127.0.0.1:8000/docs
```

健康检查：

```text
GET http://127.0.0.1:8000/api/v1/health
```

## 与 Spring Boot 的对应关系

```text
Spring Boot                 FastAPI
--------------------------------------------------
@RestController       ->    APIRouter
@RequestBody          ->    Pydantic BaseModel
@Service              ->    普通 Service 类
@Configuration        ->    core/config.py
application.yml       ->    .env + Settings
Bean 注入             ->    Depends
启动/销毁生命周期     ->    lifespan
```

## 下一步

第一阶段只学习 FastAPI + 官方 Codex SDK + Thread / Turn。

下一步再把现有 Java `order-mcp` 接进来，让链路变成：

```text
Java Business System
        ^
        | MCP
        |
Codex Harness
        ^
        |
Python Agent Service
        ^
        | HTTP
        |
Java / Web Client
```

这样 Java 业务逻辑仍然留在原业务系统里，Python 只负责 Agent Runtime。
