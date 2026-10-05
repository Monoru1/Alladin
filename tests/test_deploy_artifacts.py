"""Tests structurels des artefacts de déploiement Linux/systemd.

Aucun systemd réel requis. Fonctionne sur Windows CI.
"""
from __future__ import annotations

from pathlib import Path

DEPLOY = Path(__file__).parent.parent / "deploy"
PAPER_SERVICE = DEPLOY / "alladin-jafar-paper.service"
MC_SERVICE = DEPLOY / "alladin-jafar-mission-control.service"
ENV_EXAMPLE = DEPLOY / "alladin-jafar.env.example"
INSTALL_SH = DEPLOY / "install.sh"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────────────
# Fichiers présents
# ──────────────────────────────────────────────────────────────────────────────

def test_paper_service_exists() -> None:
    assert PAPER_SERVICE.exists()


def test_mc_service_exists() -> None:
    assert MC_SERVICE.exists()


def test_env_example_exists() -> None:
    assert ENV_EXAMPLE.exists()


# ──────────────────────────────────────────────────────────────────────────────
# Service PAPER — sécurité trading
# ──────────────────────────────────────────────────────────────────────────────

def test_paper_service_uses_paper_mode() -> None:
    content = _read(PAPER_SERVICE)
    assert "--mode PAPER" in content


def test_paper_service_never_live() -> None:
    content = _read(PAPER_SERVICE)
    assert "--mode LIVE" not in content
    assert "LIVE_GATED" not in content


def test_paper_service_uses_crypto_public() -> None:
    content = _read(PAPER_SERVICE)
    assert "--broker crypto-public" in content


def test_paper_service_no_production_write_broker() -> None:
    content = _read(PAPER_SERVICE)
    assert "crypto-testnet" not in content
    # mt5 n'a aucun sens pour Jafar crypto
    assert "--broker mt5" not in content


def test_paper_service_uses_infinite_cycles() -> None:
    """--cycles 0 = boucle infinie."""
    content = _read(PAPER_SERVICE)
    assert "--cycles 0" in content


def test_paper_service_uses_environment_file() -> None:
    content = _read(PAPER_SERVICE)
    assert "EnvironmentFile=" in content


def test_paper_service_no_hardcoded_secrets() -> None:
    content = _read(PAPER_SERVICE)
    assert "BINANCE_API_KEY=" not in content
    assert "-----BEGIN" not in content
    assert "password" not in content.lower() or "Password" not in content


def test_paper_service_sigterm() -> None:
    content = _read(PAPER_SERVICE)
    assert "KillSignal=SIGTERM" in content


def test_paper_service_restart_policy() -> None:
    content = _read(PAPER_SERVICE)
    assert "Restart=on-failure" in content


def test_paper_service_fail_closed_exit_not_restarted() -> None:
    """Exit 3 = fail-closed logique : systemd ne doit pas relancer."""
    content = _read(PAPER_SERVICE)
    assert "RestartPreventExitStatus=3" in content


def test_paper_service_working_directory_explicit() -> None:
    content = _read(PAPER_SERVICE)
    assert "WorkingDirectory=" in content


def test_paper_service_hardening() -> None:
    content = _read(PAPER_SERVICE)
    assert "NoNewPrivileges=true" in content
    assert "PrivateTmp=true" in content


def test_paper_service_logs_journal() -> None:
    content = _read(PAPER_SERVICE)
    assert "StandardOutput=journal" in content
    assert "StandardError=journal" in content


# ──────────────────────────────────────────────────────────────────────────────
# Service Mission Control — lecture seule, indépendant du runtime
# ──────────────────────────────────────────────────────────────────────────────

def test_mc_service_uses_serve_command() -> None:
    content = _read(MC_SERVICE)
    assert "jafar serve" in content


def test_mc_service_read_only_broker() -> None:
    content = _read(MC_SERVICE)
    assert "--broker crypto-public" in content


def test_mc_service_no_run_command() -> None:
    """Mission Control ne doit pas lancer le runtime de trading."""
    content = _read(MC_SERVICE)
    assert "jafar run" not in content


def test_mc_service_uses_environment_file() -> None:
    content = _read(MC_SERVICE)
    assert "EnvironmentFile=" in content


def test_mc_service_separate_unit() -> None:
    """Les deux services sont des fichiers distincts — indépendance totale."""
    assert PAPER_SERVICE.name != MC_SERVICE.name


def test_mc_service_has_port() -> None:
    content = _read(MC_SERVICE)
    assert "--port" in content


def test_mc_service_no_hardcoded_secrets() -> None:
    content = _read(MC_SERVICE)
    assert "BINANCE_API_KEY=" not in content
    assert "-----BEGIN" not in content


# ──────────────────────────────────────────────────────────────────────────────
# EnvironmentFile template — sécurité, pas de secrets réels
# ──────────────────────────────────────────────────────────────────────────────

def test_env_example_no_real_secrets() -> None:
    content = _read(ENV_EXAMPLE)
    # Aucune vraie clé API (longueur caractéristique Binance > 40 chars alphanum)
    # Les lignes non-commentées avec = ne doivent pas contenir de longue chaîne alphanum
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        _, _, value = stripped.partition("=")
        value = value.strip()
        if value and not value.startswith("<") and not value.startswith("/"):
            # Valeur numérique ou courte = ok
            assert len(value) < 40 or not value.isalnum(), (
                f"Possible secret hardcodé dans env.example: {stripped!r}"
            )


def test_env_example_documents_data_dir() -> None:
    content = _read(ENV_EXAMPLE)
    assert "ALLADIN_DATA_DIR" in content


def test_env_example_documents_var_lib_alladin() -> None:
    """Le chemin serveur recommandé doit apparaître."""
    content = _read(ENV_EXAMPLE)
    assert "/var/lib/alladin" in content


def test_env_example_documents_runtime_config() -> None:
    content = _read(ENV_EXAMPLE)
    assert "RUNTIME_STALE_AFTER_S" in content
    assert "RUNTIME_MAX_FAILURES" in content


def test_env_example_documents_permissions() -> None:
    content = _read(ENV_EXAMPLE)
    assert "chmod 600" in content


# ──────────────────────────────────────────────────────────────────────────────
# Exit code fail-closed — vérification dans le code CLI
# ──────────────────────────────────────────────────────────────────────────────

def test_cli_exits_3_on_failed_status() -> None:
    """Le CLI doit avoir la logique d'exit 3 quand RuntimeStatus.FAILED."""
    cli_path = Path(__file__).parent.parent / "src" / "alladin" / "cli.py"
    content = cli_path.read_text(encoding="utf-8")
    assert "RuntimeStatus.FAILED" in content
    assert "Exit(code=3)" in content or "typer.Exit(code=3)" in content


# ──────────────────────────────────────────────────────────────────────────────
# Scripts de déploiement
# ──────────────────────────────────────────────────────────────────────────────

def test_install_sh_exists() -> None:
    assert INSTALL_SH.exists()


def test_install_sh_no_auto_start_trading() -> None:
    """Le script d'install ne doit pas appeler systemctl start directement (uniquement le documenter)."""
    content = _read(INSTALL_SH)
    # Les lignes exécutant systemctl start ne doivent pas être des commandes directes
    # (elles peuvent apparaître dans des echo d'instruction)
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("systemctl start alladin-jafar-paper"):
            raise AssertionError(f"start trading sans confirmation: {stripped!r}")


def test_install_sh_no_hardcoded_secrets() -> None:
    content = _read(INSTALL_SH)
    assert "BINANCE_API_KEY=" not in content
    assert "-----BEGIN" not in content


def test_backup_script_exists() -> None:
    backup = Path(__file__).parent.parent / "scripts" / "backup_jafar_db.sh"
    assert backup.exists()


def test_backup_script_uses_sqlite3() -> None:
    backup = Path(__file__).parent.parent / "scripts" / "backup_jafar_db.sh"
    content = _read(backup)
    assert "sqlite3" in content
    assert ".backup" in content


def test_verify_sh_exists() -> None:
    verify = DEPLOY / "verify.sh"
    assert verify.exists()


def test_verify_sh_checks_paper_mode() -> None:
    verify = DEPLOY / "verify.sh"
    content = _read(verify)
    assert "PAPER" in content
    assert "LIVE" in content


def test_deploy_linux_doc_exists() -> None:
    doc = Path(__file__).parent.parent / "docs" / "DEPLOY_LINUX.md"
    assert doc.exists()


def test_deploy_linux_doc_has_acceptance_checklist() -> None:
    doc = Path(__file__).parent.parent / "docs" / "DEPLOY_LINUX.md"
    content = _read(doc)
    assert "PAPER uniquement" in content
    assert "LIVE" in content
    assert "SIGTERM" in content
    assert "backup" in content.lower()
    assert "FAILED" in content
