"""Workstation acceptance: consistent SQLite backup, software checks, optional MT5 reads.

No trading command, server, agent login or package installation is performed.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def backup_databases(settings: Any, destination: Path) -> list[dict[str, str]]:
    from sqlalchemy.engine import make_url

    from alladin.core.workspace import WorkspaceId

    destination.mkdir(parents=True, exist_ok=True)
    seen: set[Path] = set()
    saved = []
    for workspace in WorkspaceId:
        url = make_url(settings.for_workspace(workspace).db_url)
        if url.get_backend_name() != "sqlite":
            raise ValueError("Automatic acceptance backup supports SQLite only; back up external DB first")
        if not url.database or url.database == ":memory:":
            continue
        source = Path(url.database).resolve()
        if source in seen or not source.exists():
            continue
        seen.add(source)
        target = destination / f"{workspace.value}-{source.name}"
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=10)) as original, closing(sqlite3.connect(target)) as copied:
            original.backup(copied)
            if copied.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError(f"Backup integrity check failed: {target.name}")
        saved.append({"workspace": workspace.value, "source": str(source), "backup": str(target)})
    return saved


def run_check(name: str, args: list[str], destination: Path) -> dict[str, Any]:
    log = destination / f"{name}.log"
    print(f"[{name}] running — {log}", flush=True)
    with log.open("w", encoding="utf-8") as stream:
        process = subprocess.run([sys.executable, *args], cwd=ROOT, stdout=stream,
                                 stderr=subprocess.STDOUT, check=False)
    print(f"[{name}] {'PASS' if process.returncode == 0 else 'FAIL'}", flush=True)
    return {"name": name, "exit_code": process.returncode, "log": str(log)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mt5-readonly", action="store_true", help="Read-only tests on a connected DEMO terminal")
    parser.add_argument("--backup-only", action="store_true", help="Back up the DBs without running checks")
    args = parser.parse_args()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    destination = ROOT / "acceptance_reports" / stamp
    destination.mkdir(parents=True, exist_ok=False)
    report: dict[str, Any] = {"created_at": stamp, "orders_sent_by_script": False,
                              "mt5_readonly_requested": args.mt5_readonly, "backups": [], "checks": []}
    try:
        from alladin.core.config import get_settings
        report["backups"] = backup_databases(get_settings(), destination / "backups")
        if not args.backup_only:
            checks = [("ruff", ["-m", "ruff", "check", "src", "tests", "scripts"]),
                      ("mypy", ["-m", "mypy", "src"]),
                      ("software", ["-m", "pytest", "-ra"])]
            if args.mt5_readonly:
                checks.append(("mt5_readonly", ["-m", "pytest", "tests/integration/test_mt5_live.py", "--run-mt5", "-ra"]))
            report["checks"] = [run_check(name, command, destination) for name, command in checks]
    except Exception as exc:
        report["error"] = str(exc)
        print(f"Acceptance stopped: {exc}", file=sys.stderr)
    report_file = destination / "report.json"
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report: {report_file}", flush=True)
    return 1 if report.get("error") or any(c["exit_code"] for c in report["checks"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
