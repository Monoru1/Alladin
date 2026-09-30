"""Adapters d'agents par subprocess (CLI locaux sous abonnement — aucune clé API requise).

Sécurité :
  - environnement ASSAINI par liste blanche : ni MT5_*, ni clés API, ni secrets du .env ;
  - cwd = répertoire temporaire vide : l'agent ne voit ni le dépôt ni le .env ;
  - prompt via stdin ; aucun outil autorisé ; timeout strict.
Limite assumée : on s'appuie sur la session déjà connectée du CLI (login d'abonnement). Si elle est
absente ou expirée, l'adapter renvoie une erreur explicite ; on ne contourne RIEN (pas de scraping web).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from abc import abstractmethod
from collections.abc import Callable
from typing import Any

from alladin.agents.base import AgentAdapter, AgentRequest, AgentResponse, build_prompt, parse_agent_text

_ENV_WHITELIST = {
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP", "USERPROFILE",
    "HOME", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES",
    "PROGRAMFILES(X86)", "USERNAME", "COMPUTERNAME", "LANG", "TERM", "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE", "OS",
}  # fmt: skip

Runner = Callable[..., subprocess.CompletedProcess[str]]


def sanitized_env(source: dict[str, str] | None = None) -> dict[str, str]:
    src = source if source is not None else dict(os.environ)
    return {k: v for k, v in src.items() if k.upper() in _ENV_WHITELIST}


class SubprocessAgent(AgentAdapter):
    executable: str

    def __init__(self, timeout_s: int = 180, runner: Runner | None = None, model: str | None = None) -> None:
        self.timeout_s = timeout_s
        self.runner: Runner = runner or subprocess.run
        self.model = model

    @abstractmethod
    def build_command(self, exe: str, workdir: str) -> list[str]: ...

    @abstractmethod
    def extract_text(self, stdout: str, workdir: str) -> str: ...

    def resolve_executable(self) -> str | None:
        return shutil.which(self.executable)

    def propose(self, request: AgentRequest) -> AgentResponse:
        exe = self.resolve_executable()
        if exe is None:
            return AgentResponse(
                agent=self.name, errors=[f"CLI '{self.executable}' introuvable dans le PATH"]
            )
        prompt = build_prompt(request)
        start = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="alladin-agent-") as workdir:
            cmd = self.build_command(exe, workdir)
            try:
                proc = self.runner(
                    cmd,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=self.timeout_s,
                    cwd=workdir,
                    env=sanitized_env(),
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return AgentResponse(
                    agent=self.name,
                    errors=[f"timeout après {self.timeout_s}s"],
                    duration_s=time.monotonic() - start,
                )
            except OSError as exc:
                return AgentResponse(agent=self.name, errors=[f"lancement impossible : {exc}"])
            dur = time.monotonic() - start
            if proc.returncode != 0:
                tail = (proc.stderr or proc.stdout or "").strip()[-400:]
                return AgentResponse(
                    agent=self.name,
                    errors=[f"{self.executable} a échoué (code {proc.returncode}) : {tail}"],
                    duration_s=dur,
                )
            text = self.extract_text(proc.stdout or "", workdir)
        return parse_agent_text(self.name, text, dur)


def _json_field(stdout: str, field: str) -> str | None:
    import json

    try:
        data: Any = json.loads(stdout)
    except ValueError:
        return None
    if isinstance(data, dict) and isinstance(data.get(field), str):
        return data[field]  # type: ignore[no-any-return]
    return None
