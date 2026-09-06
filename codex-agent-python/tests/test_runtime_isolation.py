import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from app.runtime import launcher
from app.runtime.policy import business_runtime_config


def test_real_exec_replaces_inherited_business_environment():
    # Separate Python process, actual execve into another executable; only test markers.
    source = """
import sys
from unittest.mock import patch
from app.runtime.launcher import main
keys = ['API_SHARED_SECRET', 'DATABASE_URL', 'EXECUTION_SERVICE_SECRET', 'OPENAI_API_KEY']
probe = 'import os,json; print(json.dumps({k: k in os.environ for k in ' + repr(keys) + '}))'
sys.argv = ['launcher', '-c', probe]
with patch('openai_codex.client._resolve_codex_bin', return_value=sys.executable):
    main()
"""
    env = dict(os.environ) | {
        name: "test-marker"
        for name in (
            "API_SHARED_SECRET",
            "DATABASE_URL",
            "EXECUTION_SERVICE_SECRET",
            "OPENAI_API_KEY",
        )
    }
    result = subprocess.run(
        [sys.executable, "-c", source],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert json.loads(result.stdout) == {
        "API_SHARED_SECRET": False,
        "DATABASE_URL": False,
        "EXECUTION_SERVICE_SECRET": False,
        "OPENAI_API_KEY": True,
    }


def test_pinned_cli_accepts_restricted_capability_config(tmp_path):
    args = [sys.executable, "-I", str(Path(launcher.__file__).resolve())]
    for key, value in business_runtime_config().items():
        args.extend(["--config", f"{key}={json.dumps(value)}"])
    args.extend(["features", "list"])
    result = subprocess.run(
        args,
        env={
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(tmp_path),
            "CODEX_HOME": str(tmp_path),
        },
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert any(
        line.startswith("shell_tool") and line.rstrip().endswith("false")
        for line in result.stdout.splitlines()
    )


def test_runtime_uses_isolated_launcher_and_refuses_writable_policy(tmp_path):
    import pytest

    from app.agents.definition import AgentDefinition, SandboxPolicy
    from app.runtime.codex_runtime import CodexRuntime

    with patch("app.runtime.codex_runtime.AsyncCodex") as sdk:
        CodexRuntime(
            AgentDefinition("test", str(tmp_path), SandboxPolicy.READ_ONLY, ()),
            tmp_path / "home",
            lambda *args: {},
        )
        config = sdk.call_args.kwargs["config"]
        assert config.launch_args_override[:2] == (sys.executable, "-I")
        assert set(config.env) == {"CODEX_HOME"}
        with pytest.raises(ValueError):
            CodexRuntime(
                AgentDefinition("test", str(tmp_path), SandboxPolicy.FULL_ACCESS, ()),
                tmp_path / "home",
                lambda *args: {},
            )
