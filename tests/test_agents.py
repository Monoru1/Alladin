"""AgentAdapter : Mock, CLI (Claude/Codex) via faux subprocess, extraction JSON, isolation des secrets."""

from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from alladin.agents.base import AgentRequest, extract_json_object, parse_agent_text
from alladin.agents.claude import ClaudeAdapter
from alladin.agents.cli import sanitized_env
from alladin.agents.codex import CodexAdapter
from alladin.agents.mock import MockAgent
from alladin.core.enums import DecisionKind

GOOD = {
    "decision": "TRADE", "reason": "tendance propre",
    "intent": {"instrument": "GBPJPY", "side": "BUY", "strategy_id": "TREND-01", "strategy_version": "1.0.0",
               "market_regime": "TREND", "entry": 211.9, "stop_loss": 211.3, "take_profit": 213.1,
               "requested_risk_pct_of_working_capital": 4.5, "confidence": 0.76, "reason": "x"},
}  # fmt: skip
REQ = AgentRequest(run_id="RUN-001", context={"shortlist": [], "signals": []})


def test_extract_json_handles_fences_and_chatter() -> None:
    assert extract_json_object('Voici:\n```json\n{"a": {"b": 1}}\n```\nfin') == {"a": {"b": 1}}
    assert extract_json_object('blabla {"x": "}"} encore') == {"x": "}"}
    assert extract_json_object("pas de json") is None


def test_parse_agent_text_good_and_bad() -> None:
    ok = parse_agent_text("claude", json.dumps(GOOD))
    assert ok.ok and ok.decision and ok.decision.intent and ok.decision.intent.instrument == "GBPJPY"
    no = parse_agent_text("claude", '{"decision": "NO_TRADE", "reason": "range"}')
    assert no.ok and no.decision and no.decision.decision is DecisionKind.NO_TRADE
    assert not parse_agent_text("claude", "rien").ok
    assert not parse_agent_text("claude", '{"decision": "TRADE", "reason": "sans intent"}').ok


def test_agent_output_with_volume_or_unknown_field_is_invalid() -> None:
    bad = json.loads(json.dumps(GOOD))
    bad["intent"]["volume"] = 10
    resp = parse_agent_text("claude", json.dumps(bad))
    assert not resp.ok and any("volume" in e for e in resp.errors)


def test_mock_agent_default_no_trade_and_scripted() -> None:
    agent = MockAgent()
    assert agent.propose(REQ).decision.decision is DecisionKind.NO_TRADE  # type: ignore[union-attr]
    signal = {"draft": {**GOOD["intent"], "confidence": 0.8}}  # type: ignore[dict-item]
    r = agent.propose(
        AgentRequest(
            run_id="R", context={"signals": [signal, {"draft": {**GOOD["intent"], "confidence": 0.5}}]}
        )
    )  # type: ignore[dict-item]
    assert (
        r.decision
        and r.decision.decision is DecisionKind.TRADE
        and r.decision.intent
        and r.decision.intent.confidence == 0.8
    )


def test_sanitized_env_drops_credentials_and_api_keys() -> None:
    env = sanitized_env({"PATH": "/bin", "USERPROFILE": "C:/u", "MT5_PASSWORD": "x", "MT5_LOGIN": "1",
                         "ANTHROPIC_API_KEY": "k", "OPENAI_API_KEY": "k", "DATABASE_URL": "x"})  # fmt: skip
    assert env == {"PATH": "/bin", "USERPROFILE": "C:/u"}


class Recorder:
    def __init__(
        self,
        stdout: str = "",
        returncode: int = 0,
        raises: Exception | None = None,
        write_last: str | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.stdout, self.returncode, self.raises, self.write_last = stdout, returncode, raises, write_last

    def __call__(self, cmd: list[str], **kw: Any) -> Any:
        self.calls.append({"cmd": cmd, **kw})
        if self.raises:
            raise self.raises
        if self.write_last is not None:
            Path(cmd[cmd.index("-o") + 1]).write_text(self.write_last, encoding="utf-8")
        return SimpleNamespace(returncode=self.returncode, stdout=self.stdout, stderr="boom")


def test_claude_adapter_subprocess_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MT5_PASSWORD", "topsecret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    monkeypatch.setattr("shutil.which", lambda _: "C:/bin/claude.exe")
    rec = Recorder(stdout=json.dumps({"type": "result", "result": "```json\n" + json.dumps(GOOD) + "\n```"}))
    resp = ClaudeAdapter(runner=rec).propose(REQ)
    assert resp.ok and resp.decision and resp.decision.intent and resp.decision.intent.instrument == "GBPJPY"
    call = rec.calls[0]
    assert call["cmd"][:2] == ["C:/bin/claude.exe", "-p"] and "--tools" in call["cmd"]
    assert (
        call["env"].get("MT5_PASSWORD") is None and "ANTHROPIC_API_KEY" not in call["env"]
    )  # pas de secret, pas d'API payante
    assert "topsecret" not in call["input"]
    assert (
        Path(call["cwd"]).name.startswith("alladin-agent-") and "Alladin" not in call["cwd"]
    )  # cwd neutre, pas le dépôt


def test_codex_adapter_reads_last_message_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _: "C:/bin/codex.exe")
    rec = Recorder(stdout="logs bruyants", write_last=json.dumps(GOOD))
    resp = CodexAdapter(runner=rec).propose(REQ)
    assert resp.ok and resp.decision and resp.decision.intent
    cmd = rec.calls[0]["cmd"]
    assert cmd[1] == "exec" and "read-only" in cmd and "--ephemeral" in cmd and cmd[-1] == "-"


def test_cli_adapters_report_problems_instead_of_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _: None)
    assert "introuvable" in ClaudeAdapter().propose(REQ).errors[0]
    monkeypatch.setattr("shutil.which", lambda _: "x")
    assert (
        "timeout"
        in ClaudeAdapter(runner=Recorder(raises=subprocess.TimeoutExpired("x", 1))).propose(REQ).errors[0]
    )
    assert "code 1" in ClaudeAdapter(runner=Recorder(returncode=1)).propose(REQ).errors[0]
    assert not ClaudeAdapter(runner=Recorder(stdout='{"result": "du texte sans json"}')).propose(REQ).ok


def test_agents_package_cannot_reach_brokers_or_the_approval_token() -> None:
    """Garantie structurelle : aucun module d'agent n'importe broker, exécution, risque ou jeton d'approbation."""
    forbidden = (
        "alladin.brokers",
        "alladin.execution",
        "alladin.risk",
        "alladin.core.approval",
        "alladin.orchestration",
        "MetaTrader5",
    )
    root = Path(__file__).resolve().parents[1] / "src" / "alladin" / "agents"
    offenders = []
    for py in root.glob("*.py"):
        for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
            names = (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else []
            )
            offenders += [f"{py.name}: {n}" for n in names if n.startswith(forbidden)]
    assert offenders == []
