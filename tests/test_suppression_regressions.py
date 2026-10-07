import pytest

from specprobe.demo import build_spec
from specprobe.rules.oracle import State, step
from specprobe.sim.ecu import EcuSimulator


@pytest.mark.parametrize("supported,expected", [(False, b"\x7e\x00"), (True, None)])
def test_tester_present_respects_configured_suppression(supported, expected):
    spec = build_spec()
    spec.service(0x3E).suppress_positive_response_supported = supported
    response, _ = step(spec, State(1), {}, b"\x3e\x80")
    assert response.bytes == expected
    assert EcuSimulator(spec).send(b"\x3e\x80") == expected


@pytest.mark.parametrize("supported,expected", [(False, b"\x50\x03\x00\x32\x01\xf4"), (True, None)])
def test_session_suppression_keeps_subfunction_and_state(supported, expected):
    spec = build_spec()
    spec.service(0x10).suppress_positive_response_supported = supported
    response, state = step(spec, State(1), {}, b"\x10\x83")
    assert response.bytes == expected and state.session == 3
    simulator = EcuSimulator(spec)
    assert simulator.send(b"\x10\x83") == expected
    assert simulator.state.session == 3


def test_suppression_never_hides_a_negative_response():
    spec = build_spec()
    spec.service(0x10).suppress_positive_response_supported = True
    response, _ = step(spec, State(1), {}, b"\x10\x83\x00")
    assert response.bytes == b"\x7f\x10\x13"
    assert EcuSimulator(spec).send(b"\x10\x83\x00") == response.bytes
