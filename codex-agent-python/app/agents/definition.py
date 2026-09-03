from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SandboxPolicy(str, Enum):
    """单 Agent 的本地运行权限。"""

    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    FULL_ACCESS = "full_access"


@dataclass(frozen=True, slots=True)
class McpServerDefinition:
    """当前单 Agent 可使用的一个 MCP Server 及 Tool Policy。"""

    name: str
    url: str
    enabled_tools: tuple[str, ...]
    tool_approval_modes: tuple[tuple[str, str], ...]
    default_approval_mode: str = "approve"

    def __post_init__(self) -> None:
        if not self.name or not self.name.replace("_", "").replace("-", "").isalnum():
            raise ValueError("MCP Server name 只能包含字母、数字、_、-")
        if not self.url:
            raise ValueError("MCP Server url 不能为空")
        if not self.enabled_tools:
            raise ValueError("MCP Server 至少需要暴露一个 Tool")

        allowed_modes = {"auto", "prompt", "writes", "approve"}
        if self.default_approval_mode not in allowed_modes:
            raise ValueError("非法的 MCP 默认审批模式")

        enabled = set(self.enabled_tools)
        for tool_name, approval_mode in self.tool_approval_modes:
            if tool_name not in enabled:
                raise ValueError(f"Tool {tool_name} 不在 enabled_tools 中")
            if approval_mode not in allowed_modes:
                raise ValueError(f"Tool {tool_name} 的审批模式非法")


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    """当前唯一业务 Agent 的运行定义。

    这里只有内容层和最小运行策略：workspace、sandbox、MCP、Tool Policy。
    不承担 Agent Registry、Runtime Router 或多 Agent Control Plane 职责。
    """

    agent_id: str
    workspace: str
    sandbox: SandboxPolicy
    mcp_servers: tuple[McpServerDefinition, ...]

    def __post_init__(self) -> None:
        if not self.agent_id:
            raise ValueError("agent_id 不能为空")
        if not self.workspace:
            raise ValueError("workspace 不能为空")
        names = [server.name for server in self.mcp_servers]
        if len(names) != len(set(names)):
            raise ValueError("MCP Server name 不能重复")
