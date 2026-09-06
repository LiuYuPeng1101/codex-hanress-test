"""Trusted exec boundary: SDK 0.147 merges os.environ even when config.env is supplied.

Run via Python -I and an absolute path. Only runtime/model authentication enters
Codex; business service credentials and arbitrary host variables are removed.
This is not an OS sandbox for agents that need arbitrary local code execution.
"""

import os
import sys

# Explicit allowlist; never accept wildcard env passthrough from a prompt/config.
RUNTIME_ENV_KEYS = frozenset(
    {
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "SYSTEMROOT",
        "WINDIR",
        "CODEX_HOME",
        "OPENAI_API_KEY",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    }
)


def runtime_environment(source: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in source.items() if key in RUNTIME_ENV_KEYS}


def main() -> None:
    # Drop unrelated credentials before loading the SDK resolver or the real executable.
    clean = runtime_environment(dict(os.environ))
    os.environ.clear()
    os.environ.update(clean)
    from openai_codex import CodexConfig
    from openai_codex.client import _resolve_codex_bin

    binary = str(_resolve_codex_bin(CodexConfig()))
    os.execve(binary, [binary, *sys.argv[1:]], clean)


if __name__ == "__main__":
    main()
