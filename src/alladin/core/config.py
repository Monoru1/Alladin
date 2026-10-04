"""Configuration applicative (variables d'environnement / .env). Aucun secret n'est loggé."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, PrivateAttr, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from alladin.core.workspace import WorkspaceId

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore", populate_by_name=True)

    _workspace_scope: WorkspaceId = PrivateAttr(default=WorkspaceId.ALLADIN)
    _workspace_root: Settings | None = PrivateAttr(default=None)

    # REAL MONEY TRADING = INTERDIT : "demo" est la seule valeur acceptée dans cette version.
    trading_mode: Literal["demo"] = Field(default="demo", alias="TRADING_MODE")

    data_dir: Path = Field(default=Path("data"), alias="ALLADIN_DATA_DIR")
    database_url: str | None = Field(default=None, alias="DATABASE_URL")
    profiles_dir: Path = Field(default=REPO_ROOT / "config" / "challenge_profiles")
    strategies_dir: Path = Field(default=REPO_ROOT / "config" / "strategies")
    reward_policy_path: Path = Field(
        default=REPO_ROOT / "config" / "reward_policies" / "outcome_v1.yaml", alias="REWARD_POLICY_PATH"
    )
    default_profile: str = Field(default="ftmo_2step_demo", alias="DEFAULT_PROFILE")

    mt5_path: str | None = Field(default=None, alias="MT5_PATH")
    mt5_login: int | None = Field(default=None, alias="MT5_LOGIN")
    mt5_password: SecretStr | None = Field(default=None, alias="MT5_PASSWORD")
    mt5_server: str | None = Field(default=None, alias="MT5_SERVER")
    mt5_timeout_ms: int = Field(default=60000, alias="MT5_TIMEOUT_MS")
    mt5_server_utc_offset_hours: float | None = Field(
        default=None, alias="MT5_SERVER_UTC_OFFSET_HOURS"
    )  # None = auto

    agent: Literal["mock", "claude", "codex"] = Field(default="mock", alias="AGENT")
    agent_timeout_s: int = Field(default=180, alias="AGENT_TIMEOUT_S")

    # Binance Jafar : jamais serialises/logges. Le chemin est configurable ; aucun contenu PEM dans Git.
    binance_api_key: SecretStr | None = Field(default=None, alias="BINANCE_API_KEY")
    jafar_binance_private_key_path: Path | None = Field(default=None, alias="JAFAR_BINANCE_PRIVATE_KEY_PATH")
    binance_recv_window_ms: int = Field(default=5000, ge=1, le=60_000, alias="BINANCE_RECV_WINDOW_MS")

    magic_base: int = 26_000_000  # magic = magic_base + numéro de run

    @field_validator(
        "mt5_login",
        "mt5_path",
        "mt5_server",
        "mt5_password",
        "database_url",
        "mt5_server_utc_offset_hours",
        "binance_api_key",
        "jafar_binance_private_key_path",
        mode="before",
    )
    @classmethod
    def _empty_to_none(cls, v: object) -> object:
        return None if v == "" else v

    def for_workspace(self, workspace: WorkspaceId) -> Settings:
        """Idempotent scope: passing component settings back cannot nest directories."""
        workspace = WorkspaceId(workspace)
        if self._workspace_scope is workspace:
            return self
        base = self._workspace_root or self
        if workspace is WorkspaceId.ALLADIN:
            return base
        scoped = base.model_copy(
            update={
                "data_dir": base.resolved_data_dir / "workspaces" / workspace.value,
                "default_profile": "jafar_observe",
                "strategies_dir": base.strategies_dir / "jafar",
            }
        )
        scoped._workspace_scope = workspace
        scoped._workspace_root = base
        return scoped

    @property
    def resolved_data_dir(self) -> Path:
        p = self.data_dir if self.data_dir.is_absolute() else REPO_ROOT / self.data_dir
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.resolved_data_dir / 'alladin.db').as_posix()}"

    @property
    def kill_switch_path(self) -> Path:
        return self.resolved_data_dir / "KILL_SWITCH"


def get_settings() -> Settings:
    return Settings()
