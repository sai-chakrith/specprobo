import pytest

from specprobe.domain.schema import Precondition
from specprobe.domain.testcase import TestCase as Case
from specprobe.gen.generator import _environment
from specprobe.ingest.extractor import extract_spec_fields
from specprobe.ingest.models import TableRow, TextBlock
from specprobe.rules.oracle import State, _conditions_hold
from specprobe.runner.executor import run_suite


@pytest.mark.parametrize("value", [True, False, 4, 4.5, "park"])
def test_negative_not_equal_violates_condition(value):
    condition = Precondition(
        kind="signal", signal="s", op="!=", value=value, source_text="s differs"
    )
    assert not _conditions_hold([condition], State(session=1), _environment([condition], False))


def test_compound_positive_environment_satisfies_shared_signal_bounds():
    conditions = [
        Precondition(kind="signal", signal="s", op=op, value=value, source_text="bound")
        for op, value in [(">", 0), ("<", 0.1), ("!=", 0.05)]
    ]
    assert _conditions_hold(conditions, State(session=1), _environment(conditions, True))


def test_prose_condition_maps_to_did_and_routine_with_same_identifier():
    rows = [
        TableRow("doc", {"DID": "0x1000", "Bytes": 2}, page=2),
        TableRow(
            "doc",
            {
                "Routine identifier": "0x1000",
                "Operation": "Erase",
                "Controls": "1",
                "Parameter octets": "{1: 0}",
            },
            sheet="Routines",
            row=4,
        ),
    ]
    blocks = [
        TextBlock("doc", "DID 0x1000 may be written only when speed is below 2.5 km/h.", page=5),
        TextBlock("doc", "Routine 0x1000 requires ready to be true.", page=6),
    ]
    fields = extract_spec_fields("doc", rows, blocks)
    did = next(f for f in fields if f.path == "dids[0].preconditions")
    routine = next(f for f in fields if f.path == "routines[0].preconditions")
    assert did.value[0]["value"] == 2.5
    assert did.provenance.page == 5
    assert routine.value[0]["signal"] == "ready"


class Replay:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def set_environment(self, environment):
        pass

    def send(self, request):
        self.requests.append(request)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def case(**updates):
    return Case(
        id="regression",
        trace_to=[],
        preconditions={},
        setup_steps=[b"\x10\x03"],
        setup_expected=[b"\x50\x03"],
        steps=[b"\x3e\x00"],
        step_expected=[b"\x7e\x00"],
        expected=b"\x7e\x00",
        tags=[],
        **updates,
    )


def test_setup_failure_cannot_be_hidden_by_matching_final_response():
    transport = Replay([b"\x7f\x10\x31", b"\x7e\x00"])
    result = run_suite([case()], transport)[0]
    assert not result.passed
    assert result.failure_kind == "setup_failure"
    assert len(transport.requests) == 1


def test_communication_error_becomes_structured_result():
    result = run_suite([case()], Replay([TimeoutError("timeout")]))[0]
    assert result.failure_kind == "communication_failure"


def test_intermediate_mismatch_cannot_be_hidden():
    value = Case(
        id="intermediate",
        trace_to=[],
        preconditions={},
        setup_steps=[],
        steps=[b"\x10\x03", b"\x3e\x00"],
        step_expected=[b"\x50\x03", b"\x7e\x00"],
        expected=b"\x7e\x00",
        tags=[],
    )
    assert (
        run_suite([value], Replay([b"\x50\x01", b"\x7e\x00"]))[0].failure_kind
        == "response_mismatch"
    )
