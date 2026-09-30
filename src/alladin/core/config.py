"""Configuration applicative (variables d'environnement / .env). Aucun secret n'est loggé."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore", populate_by_name=True)

    # REAL MONEY TRADING = INTERDIT : "demo" est la seule valeur acceptée dans cette version.
    trading_mode: Literal["demo"] = Field(default="demo", alias="TRADING_MODE")

    data_dir: Path = Field(default=Path("data"), alias="ALLADIN_DATA_DIR")
    database_url: str | None = Field(default=None, alias="DATABASE_URL")
    profiles_dir: Path = Field(default=REPO_ROOT / "config" / "challenge_profiles")
    strategies_dir: Path = Field(default=REPO_ROOT / "config" / "strategies")
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

    magic_base: int = 26_000_000  # magic = magic_base + numéro de run

    @field_validator(
        "mt5_login",
        "mt5_path",
        "mt5_server",
        "mt5_password",
        "database_url",
        "mt5_server_utc_offset_hours",
        mode="before",
    )
    @classmethod
    def _empty_to_none(cls, v: object) -> object:
        return None if v == "" else v

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
