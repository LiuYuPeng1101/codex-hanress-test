from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from openai_codex import Sandbox


@dataclass(frozen=True, slots=True)
class McpToolPolicy:
    """单个 MCP Tool 的治理策略。"""

    name: str
    approval_mode: str
    output_token_limit: int


@dataclass(frozen=True, slots=True)
class McpServerDefinition:
    """Agent 可访问的一个 MCP Server。"""

    name: str
    url: str
    tools: tuple[McpToolPolicy, ...]
    default_approval_mode: str = "prompt"
    required: bool = True
    startup_timeout_sec: int = 10
    tool_timeout_sec: int = 30


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    """一个可运行 Agent 的生产配置。

    CodexRuntime 只消费这个定义，不应该知道订单、合同、财务等业务名称。
    """

    id: str
    workspace: Path
    sandbox: Sandbox
    required_skills: tuple[str, ...]
    mcp_servers: tuple[McpServerDefinition, ...]


def build_order_agent(*, workspace: Path, order_mcp_url: str) -> AgentDefinition:
    """构建订单 Agent Definition。"""

    return AgentDefinition(
        id="order",
        workspace=workspace.resolve(),
        sandbox=Sandbox.read_only,
        required_skills=("order-analysis",),
        mcp_servers=(
            McpServerDefinition(
                name="order",
                url=order_mcp_url,
                default_approval_mode="prompt",
                required=True,
                startup_timeout_sec=10,
                tool_timeout_sec=30,
                tools=(
                    McpToolPolicy("get_order_status", "approve", 1024),
                    McpToolPolicy("cancel_order", "prompt", 1024),
                ),
            ),
        ),
    )
