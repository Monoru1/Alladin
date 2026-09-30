"""ClaudeAdapter : appelle le CLI local `claude` (Claude Code) en mode non interactif."""

from __future__ import annotations

from alladin.agents.cli import SubprocessAgent, _json_field


class ClaudeAdapter(SubprocessAgent):
    name = "claude"
    executable = "claude"

    def build_command(self, exe: str, workdir: str) -> list[str]:
        cmd = [
            exe,
            "-p",
            "--output-format",
            "json",
            "--tools",
            "",
            "--no-session-persistence",
            "--max-turns",
            "1",
            # isolement : ni hooks/plugins/MCP/skills de l'utilisateur (ils perturbent ou font échouer l'appel)
            "--setting-sources",
            "project,local",
            "--strict-mcp-config",
            "--disable-slash-commands",
        ]
        if self.model:
            cmd += ["--model", self.model]
        return cmd

    def extract_text(self, stdout: str, workdir: str) -> str:
        return _json_field(stdout, "result") or stdout
