import pytest

from specprobe.demo import build_spec
from specprobe.domain.testcase import TestCase as Case
from specprobe.gen.generator import generate_suite
from specprobe.runner.executor import run_suite
from tests.test_correctness_regressions import Replay


def test_missing_setup_expectations_block_before_communication():
    case = Case(
        id="missing",
        trace_to=[],
        preconditions={},
        setup_steps=[b"\x10\x03"],
        steps=[b"\x3e\x00"],
        expected=b"\x7e\x00",
        tags=[],
    )
    transport = Replay([b"\x50\x01", b"\x7e\x00"])
    result = run_suite([case], transport)[0]
    assert result.failure_kind == "configuration_failure"
    assert transport.requests == []


def test_generation_rejects_setup_that_cannot_establish_requested_state():
    spec = build_spec()
    spec.service(0x27).allowed_sessions = [3]
    with pytest.raises(ValueError, match="Setup"):
        generate_suite(spec)
