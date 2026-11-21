"""Reading and writing the files of one analysis folder (analyses/<TICKER>/<data-base>/)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ValidationError

from engine.contract import AnalysisData
from engine.contract.indicators import IndicatorsReport
from engine.contract.validation import ValidationReport
from engine.snapshot.build import ANALYSES_DIR


class AnalysisStateError(RuntimeError):
    """The analysis folder is missing a step or its files do not belong together."""


@dataclass(frozen=True)
class AnalysisFolder:
    path: Path
    data: AnalysisData

    @classmethod
    def latest(cls, ticker: str, root: Path = ANALYSES_DIR) -> AnalysisFolder:
        folder = root / ticker.upper()
        candidates = sorted(p for p in folder.glob("*") if (p / "data.json").exists())
        if not candidates:
            raise AnalysisStateError(
                f"nenhum snapshot de {ticker.upper()} — rode: skillsinvest snapshot {ticker}"
            )
        path = candidates[-1]
        try:
            data = AnalysisData.model_validate_json(
                (path / "data.json").read_text(encoding="utf-8")
            )
        except ValidationError as exc:
            raise AnalysisStateError(
                f"{path / 'data.json'} não segue o contrato atual — rode: skillsinvest snapshot "
                f"{ticker.upper()} ({exc.error_count()} erro(s))"
            ) from exc
        return cls(path=path, data=data)

    def validation(self) -> ValidationReport:
        """The validation of this exact snapshot; refuses a blocking or stale one."""
        file = self.path / "validation.json"
        if not file.exists():
            raise AnalysisStateError("snapshot sem validação — rode: skillsinvest validate")
        report = ValidationReport.model_validate_json(file.read_text(encoding="utf-8"))
        if report.snapshot_as_of != self.data.as_of:
            raise AnalysisStateError(
                "validation.json é de outro snapshot — rode: skillsinvest validate"
            )
        if report.blocking:
            raise AnalysisStateError("a validação tem erros que bloqueiam os valuations")
        return report

    def indicators(self) -> IndicatorsReport:
        file = self.path / "indicators.json"
        if not file.exists():
            raise AnalysisStateError("snapshot sem indicadores — rode: skillsinvest indicators")
        report = IndicatorsReport.model_validate_json(file.read_text(encoding="utf-8"))
        if report.snapshot_as_of != self.data.as_of:
            raise AnalysisStateError(
                "indicators.json é de outro snapshot — rode: skillsinvest indicators"
            )
        return report

    def write(self, relative: str, model: BaseModel) -> Path:
        file = self.path / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(model.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return file
