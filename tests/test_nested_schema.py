import pytest

from specprobe.demo import build_spec
from specprobe.domain.schema import EcuSpec


def test_unknown_nested_specification_fields_are_not_silently_discarded():
    data = build_spec().model_dump()
    data["services"][0]["required_security_levle"] = 1
    with pytest.raises(ValueError):
        EcuSpec.model_validate(data)
