"""Chargement des ChallengeProfile depuis config/challenge_profiles/*.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml

from alladin.challenge.models import ChallengeProfile
from alladin.core.errors import ConfigError


def load_profile(profile_id: str, profiles_dir: Path) -> ChallengeProfile:
    path = profiles_dir / f"{profile_id}.yaml"
    if not path.is_file():
        available = ", ".join(sorted(p.stem for p in profiles_dir.glob("*.yaml"))) or "aucun"
        raise ConfigError(f"profil introuvable : {profile_id} (disponibles : {available})")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    profile = ChallengeProfile.model_validate(data)
    if profile.id != profile_id:
        raise ConfigError(f"{path.name} : id '{profile.id}' != nom de fichier '{profile_id}'")
    return profile


def list_profiles(profiles_dir: Path) -> list[str]:
    return sorted(p.stem for p in profiles_dir.glob("*.yaml"))
