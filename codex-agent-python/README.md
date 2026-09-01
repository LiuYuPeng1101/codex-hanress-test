# Codex Agent Python

这是一个标准的 FastAPI Agent Service 示例，用来演示：

> 已有 Java / Spring Boot 业务系统时，如何使用 Python + FastAPI + 官方 OpenAI Codex Python SDK 开发独立 Agent Service，再通过 MCP 调用 Java 业务能力。

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
│   │   └── codex_runtime.py     # 官方 Codex SDK 适配层 + MCP 配置
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

## 当前架构

```text
Java / Web Client
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
        +------ MCP Client
                  |
                  v
        Java Business System
                  |
                  v
            MCP Adapter
                  |
                  v
          Business Service
```

当前示例中，Java `hanress-test` 模块扮演已有业务系统，并通过：

```text
http://127.0.0.1:8080/mcp
```

暴露订单 MCP Server。

Python Agent Service 当前只允许 Codex 使用只读 Tool：

```text
get_order_status
```

`cancel_order` 暂不开放给 Python Agent。原因是写操作需要单独设计 Approval / Human-in-the-loop，不能把学习阶段的自动批准当成生产安全方案。

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

## Codex 如何连接 Java MCP

环境变量：

```text
ORDER_MCP_URL=http://127.0.0.1:8080/mcp
```

`CodexRuntime` 创建 `AsyncCodex` 时通过官方 `CodexConfig.config_overrides` 注入 MCP 配置：

```text
mcp_servers.order.url=<ORDER_MCP_URL>
mcp_servers.order.enabled_tools=["get_order_status"]
mcp_servers.order.default_tools_approval_mode="approve"
```

因此不是 Python 自己用 `httpx` 调 Java Tool，而是：

```text
模型
 ↓
Codex Harness
 ↓
MCP Tool Discovery / Tool Call
 ↓
Java MCP Server
 ↓
业务 Service
```

这样 Tool Schema、Tool 调用和结果回模型仍由 Harness 统一管理。

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
  "message": "订单1001现在是什么状态？"
}
```

正常链路应是：

```text
用户问题
  ↓
order-analysis Skill
  ↓
要求不要猜实时订单状态
  ↓
Codex Harness 选择 get_order_status
  ↓
Java MCP Server
  ↓
OrderService
  ↓
Tool Result
  ↓
模型生成最终答案
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

## 本地 / Codespaces 联调

先启动 Java 业务系统：

```bash
cd hanress-test
./mvnw spring-boot:run
```

Java MCP Server 默认：

```text
http://127.0.0.1:8080/mcp
```

再启动 Python Agent Service：

```bash
cd codex-agent-python
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --reload
```

Windows 激活虚拟环境：

```bash
.venv\Scripts\activate
```

Swagger：

```text
http://127.0.0.1:8000/docs
```

联调顺序：

```text
1. POST /api/v1/agents/threads
2. 保存返回的 thread_id
3. POST /api/v1/agents/threads/{thread_id}/turns
4. message 输入：订单1001现在是什么状态？
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

当前阶段目标是先跑通：

```text
Python Agent
→ Codex Harness
→ Java MCP get_order_status
→ Java OrderService
→ Tool Result
→ Agent Answer
```

跑通查询链路之后，再继续做：

```text
cancel_order
→ MCP Tool Approval
→ 人工同意 / 拒绝
→ 再决定是否真正执行写操作
```

这样 Java 业务逻辑仍然留在原业务系统里，Python 只负责 Agent Runtime 与 Agent 应用层。