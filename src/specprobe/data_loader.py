import json
from pathlib import Path

from .domain.schema import EcuSpec


def load_spec(path: str | Path) -> EcuSpec:
    source = Path(path)
    return EcuSpec.model_validate(json.loads(source.read_text(encoding="utf-8")))
