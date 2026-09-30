"""Chargement des ChallengeProfile depuis config/challenge_profiles/*.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml

from alladin.challenge.models import ChallengeProfile, UniverseRules
from alladin.core.errors import ConfigError


def load_universe(ref: str, universes_dir: Path) -> UniverseRules:
    path = universes_dir / f"{ref}.yaml"
    if not path.is_file():
        available = ", ".join(sorted(p.stem for p in universes_dir.glob("*.yaml"))) or "aucun"
        raise ConfigError(f"profil d'univers introuvable : {ref} (disponibles : {available})")
    rules = UniverseRules.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    if rules.id != ref:
        raise ConfigError(f"{path.name} : id '{rules.id}' != nom de fichier '{ref}'")
    return rules


def load_profile(profile_id: str, profiles_dir: Path, universes_dir: Path | None = None) -> ChallengeProfile:
    path = profiles_dir / f"{profile_id}.yaml"
    if not path.is_file():
        available = ", ".join(sorted(p.stem for p in profiles_dir.glob("*.yaml"))) or "aucun"
        raise ConfigError(f"profil introuvable : {profile_id} (disponibles : {available})")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    ref = data.get("universe_ref")
    if ref:
        if "universe" in data:
            raise ConfigError(f"{path.name} : `universe` et `universe_ref` sont exclusifs")
        data["universe"] = load_universe(ref, universes_dir or profiles_dir.parent / "universes").model_dump()
    profile = ChallengeProfile.model_validate(data)
    if profile.id != profile_id:
        raise ConfigError(f"{path.name} : id '{profile.id}' != nom de fichier '{profile_id}'")
    return profile


def list_profiles(profiles_dir: Path) -> list[str]:
    return sorted(p.stem for p in profiles_dir.glob("*.yaml"))
