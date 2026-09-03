from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Agent Service 生产运行配置。"""

    app_name: str = "Codex Agent Service"
    app_env: str = "production"
    api_prefix: str = "/api/v1"
    agent_workspace: Path = Path(".")
    agent_id: str = "order-agent"

    runtime_instance_id: str = Field(description="当前 Runtime Worker 唯一标识")
    runtime_lease_seconds: int = Field(default=30, ge=10, le=300)
    codex_home: Path = Field(description="Codex 持久化目录；生产环境必须挂载可恢复的持久存储")

    agentgateway_llm_base_url: str = Field(
        description="Codex 模型请求经 agentgateway 暴露的 OpenAI-compatible /v1 入口"
    )
    codex_model: str = Field(default="gpt-5", description="通过 agentgateway 请求的模型名")
    agentgateway_order_mcp_url: str = Field(
        description="订单 MCP 经 agentgateway 暴露的受治理入口；禁止直连真实 MCP Adapter"
    )

    runtime_identity_private_key_path: Path = Field(
        description="签发 Runtime 短期内部 JWT 的 RSA 私钥路径"
    )
    runtime_identity_key_id: str = "runtime-key-1"
    runtime_identity_issuer: str = "agent-control-plane"
    runtime_identity_audience: str = "agentgateway"
    runtime_identity_ttl_seconds: int = Field(default=300, ge=30, le=900)

    database_url: str = Field(description="PostgreSQL 连接串")
    gateway_shared_secret: str = Field(
        min_length=32,
        description="企业 Gateway 调用 Agent Service 的服务认证密钥",
    )
    approval_timeout_seconds: int = Field(default=900, ge=30, le=86400)

    otel_exporter_otlp_traces_endpoint: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
