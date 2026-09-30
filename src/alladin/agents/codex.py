"""CodexAdapter : appelle le CLI local `codex exec` (sandbox lecture seule, sans persistance)."""

from __future__ import annotations

from pathlib import Path

from alladin.agents.cli import SubprocessAgent


class CodexAdapter(SubprocessAgent):
    name = "codex"
    executable = "codex"

    def build_command(self, exe: str, workdir: str) -> list[str]:
        cmd = [
            exe,
            "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "--cd",
            workdir,
            "-o",
            str(Path(workdir) / "last_message.txt"),
            "-",
        ]
        if self.model:
            cmd[2:2] = ["--model", self.model]
        return cmd

    def extract_text(self, stdout: str, workdir: str) -> str:
        out = Path(workdir) / "last_message.txt"
        return out.read_text(encoding="utf-8") if out.is_file() else stdout
