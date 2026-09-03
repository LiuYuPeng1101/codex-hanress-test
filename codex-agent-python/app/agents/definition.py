from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SandboxPolicy(str, Enum):
    """Agent Definition 层的运行权限，不直接依赖 Codex SDK 枚举。"""

    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    FULL_ACCESS = "full_access"


@dataclass(frozen=True, slots=True)
class McpServerDefinition:
    """Agent 通过 agentgateway 访问的一个逻辑 MCP Server。

    `url` 必须指向 agentgateway 的受治理入口，而不是真实 MCP 后端地址。
    Runtime 不保存真实后端 token；真实 credential 由 agentgateway backendAuth 管理。
    """

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

    @property
    def approval_modes(self) -> dict[str, str]:
        return dict(self.tool_approval_modes)


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    """控制面中的 Agent 定义。

    Runtime 应依赖这个稳定定义，而不是在 Codex Adapter 中写死某个订单、合同或财务 Agent。
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
            raise ValueError("Agent Definition 中 MCP Server name 不能重复")
