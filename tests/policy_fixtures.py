"""Synthetic-only contract fixtures. Never install these on a financial account."""
import json
from datetime import datetime
from pathlib import Path

from alladin.challenge.firm_policy import FirmProfile

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "policy" / "firm_profiles.json"


def load_firm_fixtures() -> dict[str, FirmProfile]:
    data = json.loads(FIXTURE_PATH.read_text())
    assert data["simulation_only"] is True and data["schema_version"] == 1
    result = {}
    for item in data["profiles"]:
        profile = item["profile"]
        for field in ("verified_at", "valid_until"):
            profile[field] = datetime.fromisoformat(profile[field])
        profile["allowed_symbols"] = frozenset(profile["allowed_symbols"])
        result[item["fixture_id"]] = FirmProfile(**profile)
    return result
