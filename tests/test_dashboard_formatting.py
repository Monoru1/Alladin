"""Run the actual money formatter to cover non-ISO reference units such as USDT."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node needed for dashboard formatter")
def test_actual_dashboard_formats_usdt_and_missing_values_without_crashing():
    html = (Path(__file__).parents[1] / "src/alladin/api/static/index.html").read_text()
    start = html.index("const money =")
    end = html.index("const pct =", start)
    script = html[start:end] + '\nconsole.log(JSON.stringify([money(1000,"USDT"),money(1000,"EUR"),money(null,"USDT"),money(NaN,"EUR")]));'
    result = subprocess.run([shutil.which("node"), "--input-type=module"], input=script,
                            text=True, capture_output=True, check=True)
    values = json.loads(result.stdout)
    assert "USDT" in values[0] and "€" in values[1]
    assert values[2:] == ["N/A", "N/A"]
