from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from openai_codex import Sandbox


@dataclass(frozen=True, slots=True)
class McpToolPolicy:
    """单个 MCP Tool 的运行策略。"""

    name: str
    approval_mode: str


@dataclass(frozen=True, slots=True)
class McpServerDefinition:
    """Agent 可访问的一个 MCP Server。"""

    name: str
    url: str
    tools: tuple[McpToolPolicy, ...]
    default_approval_mode: str = "prompt"


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    """一个可运行 Agent 的生产配置。

    Runtime 只消费这个定义，不应该知道订单、合同、财务等业务名称。
    """

    id: str
    workspace: Path
    sandbox: Sandbox
    required_skills: tuple[str, ...]
    mcp_servers: tuple[McpServerDefinition, ...]


def build_order_agent(*, workspace: Path, order_mcp_url: str) -> AgentDefinition:
    """构建订单 Agent Definition。

    订单 Agent 本地只需要读取 Skill 和工作区，因此使用 read-only Sandbox；
    查询 Tool 自动执行，写操作取消订单必须进入人工 Approval。
    """

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
                tools=(
                    McpToolPolicy("get_order_status", "approve"),
                    McpToolPolicy("cancel_order", "prompt"),
                ),
            ),
        ),
    )
