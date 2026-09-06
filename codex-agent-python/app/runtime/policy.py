"""Capability policy for a business Agent whose effects belong exclusively to MCP."""

# Verified against the pinned Codex config schema. Sandbox READ_ONLY still blocks
# apply_patch, including model families that expose it independently of feature flags.
DISABLED_FEATURES = (
    "shell_tool",
    "unified_exec",
    "shell_snapshot",
    "apply_patch_freeform",
    "js_repl",
    "code_mode",
    "code_mode_host",
    "multi_agent",
    "multi_agent_v2",
    "collab",
    "enable_fanout",
    "view_image",
    "browser_use",
    "computer_use",
    "apps",
    "plugins",
    "hooks",
    "codex_hooks",
    "plugin_hooks",
    "image_generation",
    "request_permissions_tool",
    "request_rule",
    "skill_mcp_dependency_install",
)


def business_runtime_config() -> dict:
    config = {f"features.{name}": False for name in DISABLED_FEATURES}
    config.update(
        {
            "web_search": "disabled",
            "shell_environment_policy.inherit": "none",
            "shell_environment_policy.set": {},
            "allow_login_shell": False,
        }
    )
    return config
