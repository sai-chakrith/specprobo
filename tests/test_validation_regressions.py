import pytest

from specprobe.demo import build_spec
from specprobe.domain.schema import Precondition, Subfunction
from specprobe.workflow import validate_spec


@pytest.mark.parametrize(
    "defect",
    [
        "nested_session",
        "nested_security",
        "unsupported_service",
        "routine_control",
        "negative_length",
        "missing_length",
        "unknown_unit",
        "contradiction",
    ],
)
def test_validation_rejects_unresolved_or_invalid_requirements(defect):
    spec = build_spec().model_copy(deep=True)
    if defect == "nested_session":
        spec.services[0].subfunctions = [Subfunction(value=1, name="x", allowed_sessions=[99])]
    elif defect == "nested_security":
        spec.services[0].subfunctions = [Subfunction(value=1, name="x", required_security_level=99)]
    elif defect == "unsupported_service":
        spec.services[0].sid = 0x85
    elif defect == "routine_control":
        spec.routines[0].control_types = [255]
    elif defect == "negative_length":
        spec.routines[0].parameter_lengths[1] = -1
    elif defect == "missing_length":
        spec.routines[0].parameter_lengths = {}
    elif defect == "unknown_unit":
        spec.dids[0].preconditions = [
            Precondition(
                kind="signal",
                signal="speed",
                op="<",
                value=10,
                unit="unknown",
                source_text="speed limit",
            )
        ]
    else:
        spec.dids[0].preconditions = [
            Precondition(kind="signal", signal="x", op=op, value=value, source_text="contradiction")
            for op, value in [(">", 10), ("<", 1)]
        ]
    with pytest.raises(ValueError):
        validate_spec(spec)
