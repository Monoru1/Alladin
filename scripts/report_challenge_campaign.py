"""Replay versioned synthetic challenges; no trading, accounts or random predictions."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from alladin.challenge.factory import CampaignVariant, ScenarioPath, build_campaign

ROOT = Path(__file__).resolve().parents[1]


def fixture_report(fixture: Path | None = None) -> dict[str, Any]:
    raw = (fixture or ROOT / "tests/fixtures/policy/challenge_campaign.json").read_bytes()
    data = json.loads(raw)
    if data.get("schema_version") != 1 or data.get("simulation_only") is not True:
        raise ValueError("only synthetic fixture schema 1 accepted")
    variants = tuple(CampaignVariant.model_validate(v) for v in data["variants"])
    paths = tuple(ScenarioPath.model_validate(p) for p in data["paths"])
    result = build_campaign(variants, paths)
    result["fixture_sha256"] = hashlib.sha256(raw).hexdigest()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fixture", type=Path, help="explicit simulation-only input fixture")
    args = parser.parse_args()
    text = json.dumps(fixture_report(args.fixture), indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
