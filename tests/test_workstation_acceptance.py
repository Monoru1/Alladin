import importlib.util
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from alladin.core.workspace import WorkspaceId


def script_module():
    path = Path(__file__).parents[1] / "scripts/verify_workstation.py"
    spec = importlib.util.spec_from_file_location("workstation_acceptance", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backup_includes_wal_and_does_not_migrate_original(tmp_path):
    source = tmp_path / "legacy with spaces.db"
    live = sqlite3.connect(source)
    live.execute("PRAGMA journal_mode=WAL")
    live.execute("CREATE TABLE legacy (value INTEGER)")
    live.execute("INSERT INTO legacy VALUES (42)")
    live.commit()
    settings = SimpleNamespace(for_workspace=lambda workspace: SimpleNamespace(db_url=f"sqlite:///{source}"))
    try:
        backups = script_module().backup_databases(settings, tmp_path / "backups")
        assert len(backups) == 1  # shared database is backed up once
        with sqlite3.connect(backups[0]["backup"]) as copied:
            assert copied.execute("SELECT value FROM legacy").fetchone()[0] == 42
            assert copied.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert live.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [("legacy",)]
    finally:
        live.close()


def test_backup_keeps_separate_workspace_databases(settings, tmp_path):
    for workspace in WorkspaceId:
        from sqlalchemy.engine import make_url
        file = Path(make_url(settings.for_workspace(workspace).db_url).database)
        with sqlite3.connect(file) as c:
            c.execute("CREATE TABLE marker (workspace VARCHAR)")
            c.execute("INSERT INTO marker VALUES (?)", (workspace.value,))
    backups = script_module().backup_databases(settings, tmp_path / "backups")
    assert {r["workspace"] for r in backups} == {"ALLADIN", "JAFAR"}
    for row in backups:
        with sqlite3.connect(row["backup"]) as c:
            assert c.execute("SELECT workspace FROM marker").fetchone()[0] == row["workspace"]
