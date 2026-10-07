"""A harbor agent that runs mini-swe-agent from the vendored /app/mini-swe-agent checkout.

The source lives on disk so it can be edited directly (e.g. by students). This
agent stages a filtered copy of it, uploads that into the trial environment,
and installs it from there. Everything else (CLI flags, trajectory
conversion, run()) is reused from harbor's bundled MiniSweAgent.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import override

from harbor.agents.installed.mini_swe_agent import MiniSweAgent
from harbor.environments.base import BaseEnvironment

logger = logging.getLogger(__name__)

# AIDEV-NOTE: use via `./tasks/slack-clone/run_mini_swe_local.sh`. To change
# agent behavior, edit files under LOCAL_SOURCE_DIR directly (e.g.
# src/minisweagent/agents/default.py) -- the next run installs from there.
LOCAL_SOURCE_DIR = Path(__file__).parent / "mini-swe-agent"

# Entries that don't belong in the trial environment: VCS metadata, caches,
# and build output that a stray copytree would otherwise drag along.
_IGNORE_NAMES = {".git", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules", "site"}


def _ignore_entries(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in _IGNORE_NAMES}


class MiniSweAgentLocal(MiniSweAgent):
    @staticmethod
    @override
    def name() -> str:
        return "mini-swe-agent-local"

    def _staged_source_dir(self) -> Path:
        if not LOCAL_SOURCE_DIR.is_dir():
            raise FileNotFoundError(f"Expected mini-swe-agent checkout at {LOCAL_SOURCE_DIR}")
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        staged = self.logs_dir / "mini-swe-agent-src"
        if staged.exists():
            shutil.rmtree(staged)
        shutil.copytree(LOCAL_SOURCE_DIR, staged, ignore=_ignore_entries)
        return staged

    @override
    async def install(self, environment: BaseEnvironment) -> None:
        await self.exec_as_root(
            environment,
            command=(
                "if command -v apt-get &>/dev/null; then"
                "  apt-get update && apt-get install -y curl build-essential git;"
                " elif command -v apk &>/dev/null; then"
                "  apk add --no-cache curl bash build-base git python3 py3-pip;"
                " elif command -v yum &>/dev/null; then"
                "  yum install -y curl git gcc make;"
                " elif command -v dnf &>/dev/null; then"
                "  dnf install -y curl git gcc make;"
                " else"
                '  echo "Warning: No known package manager found, assuming build tools are available" >&2;'
                " fi"
            ),
            env={"DEBIAN_FRONTEND": "noninteractive"},
        )

        remote_src = "/tmp/mini-swe-agent-src"
        await environment.upload_dir(self._staged_source_dir(), remote_src)

        await self.exec_as_agent(
            environment,
            command=(
                "set -euo pipefail; "
                "if ! command -v uv >/dev/null 2>&1; then"
                "  curl -LsSf https://astral.sh/uv/0.7.13/install.sh | sh;"
                " fi && "
                'if ! grep -q \'export PATH="$HOME/.local/bin:$PATH"\' "$HOME/.bashrc" 2>/dev/null; then'
                '  echo \'export PATH="$HOME/.local/bin:$PATH"\' >> "$HOME/.bashrc";'
                " fi && "
                'if [ -f "$HOME/.local/bin/env" ]; then source "$HOME/.local/bin/env"; fi && '
                'export PATH="$HOME/.local/bin:$PATH" && '
                f"uv tool install {remote_src} --with 'litellm[proxy]' && "
                "mini-swe-agent --help"
            ),
        )
