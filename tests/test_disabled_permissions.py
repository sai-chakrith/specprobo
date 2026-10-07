import pytest

from specprobe.demo import build_spec
from specprobe.rules.oracle import State, step
from specprobe.sim.ecu import EcuSimulator


@pytest.mark.parametrize("sid", [0x22, 0x2E])
def test_disabled_did_direction_is_not_treated_as_unrestricted(sid):
    spec = build_spec()
    did = spec.dids[6]
    did.read_security = did.write_security = None
    if sid == 0x22:
        did.read_sessions = []
    else:
        did.write_sessions = []
    request = bytes((sid, 0x10, 0x06)) + (b"\x00" * 4 if sid == 0x2E else b"")
    response, _ = step(spec, State(1), {}, request)
    assert response.bytes == bytes((0x7F, sid, 0x31))
    assert EcuSimulator(spec).send(request) == response.bytes
