"""Generates the JSON Schemas in `schemas/` from the pydantic contract models."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from engine.contract.analysis_data import AnalysisData
from engine.contract.valuation import ValuationResult
from engine.settings import PROJECT_ROOT

SCHEMAS_DIR = PROJECT_ROOT / "schemas"
JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"

CONTRACT_MODELS: dict[str, type[BaseModel]] = {
    "analysis-data": AnalysisData,
    "valuation-result": ValuationResult,
}


def render_schemas() -> dict[str, str]:
    """Return file name -> serialized JSON Schema for every contract model."""
    rendered: dict[str, str] = {}
    for name, model in CONTRACT_MODELS.items():
        schema = {"$schema": JSON_SCHEMA_DIALECT, **model.model_json_schema(mode="validation")}
        rendered[f"{name}.schema.json"] = json.dumps(schema, indent=2, ensure_ascii=False) + "\n"
    return rendered


def export_schemas(target_dir: Path = SCHEMAS_DIR) -> list[Path]:
    target_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for file_name, content in render_schemas().items():
        path = target_dir / file_name
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written


def outdated_schemas(target_dir: Path = SCHEMAS_DIR) -> list[str]:
    """File names whose content on disk differs from the current models."""
    outdated = []
    for file_name, content in render_schemas().items():
        path = target_dir / file_name
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            outdated.append(file_name)
    return outdated
