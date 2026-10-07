"""Additional hand-authored configured-data, boundary and stateful response vectors.

These validate documented model behavior. They are not approved ECU captures.
"""

import pytest

from specprobe.demo import build_spec
from specprobe.rules.oracle import State, step
from specprobe.sim.ecu import EcuSimulator


@pytest.mark.parametrize(
    "requests,expected,environment",
    [
        ([b"\x10\x03"], [b"\x50\x03\x00\x32\x01\xf4"], {}),
        ([b"\x27\x01", b"\x27\x02\xab\xcd"], [b"\x67\x01\xab\xcd", b"\x67\x02"], {}),
        (
            [b"\x27\x01", b"\x27\x02\xab\xcd", b"\x22\x10\x06"],
            [b"\x67\x01\xab\xcd", b"\x67\x02", b"\x62\x10\x06\x01\x02\x03\x04"],
            {},
        ),
        (
            [
                b"\x10\x03",
                b"\x27\x01",
                b"\x27\x02\xab\xcd",
                b"\x2e\x10\x06\x10\x20\x30\x40",
                b"\x22\x10\x06",
            ],
            [
                b"\x50\x03\x00\x32\x01\xf4",
                b"\x67\x01\xab\xcd",
                b"\x67\x02",
                b"\x6e\x10\x06",
                b"\x62\x10\x06\x10\x20\x30\x40",
            ],
            {},
        ),
        (
            [b"\x27\x01", b"\x27\x02\xab\xcd", b"\x22\x10\x01"],
            [b"\x67\x01\xab\xcd", b"\x67\x02", b"\x7f\x22\x22"],
            {"vehicle_speed": 10},
        ),
        (
            [b"\x27\x01", b"\x27\x02\xab\xcd", b"\x22\x10\x01"],
            [b"\x67\x01\xab\xcd", b"\x67\x02", b"\x62\x10\x01\x00\x00\x00\x00"],
            {"vehicle_speed": 9.99},
        ),
    ],
    ids=[
        "session-wire",
        "configured-identity-key",
        "configured-data",
        "write-read-state",
        "threshold-equality",
        "below-threshold",
    ],
)
def test_hand_authored_configured_vectors(requests, expected, environment):
    spec = build_spec()
    spec.dids[1].read_preconditions = spec.dids[1].preconditions
    spec.response_profile.did_data = {0x1006: "01020304"}
    spec.response_profile.seeds = {1: "abcd"}
    spec.response_profile.key_algorithm = "identity"
    simulator = EcuSimulator(spec)
    simulator.set_environment(environment)
    state = State(1)
    for request, wanted in zip(requests, expected, strict=True):
        actual, state = step(spec, state, environment, request)
        assert actual.bytes == wanted
        assert simulator.send(request) == wanted
