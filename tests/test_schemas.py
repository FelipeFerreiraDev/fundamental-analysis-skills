from __future__ import annotations

import json

from engine.contract.export import SCHEMAS_DIR, outdated_schemas, render_schemas


def test_exported_schemas_are_up_to_date():
    assert outdated_schemas(SCHEMAS_DIR) == [], "rode: skillsinvest export-schemas"


def test_schemas_are_valid_json_with_dialect():
    for content in render_schemas().values():
        schema = json.loads(content)
        assert schema["$schema"].startswith("https://json-schema.org/")
        assert schema["properties"]["schema_version"]["const"] == "0.3.0"
