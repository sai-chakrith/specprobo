from specprobe.demo import build_spec
from specprobe.rules.oracle import State, step
from specprobe.sim.ecu import EcuSimulator


def test_declared_nrc_priority_resolves_competing_service_failures():
    spec = build_spec()
    spec.nrc_priority.remove(0x33)
    spec.nrc_priority.insert(0, 0x33)
    request = b"\x31\x01\x20\x00\x00"
    expected, _ = step(spec, State(1), {}, request)
    assert expected.bytes == b"\x7f\x31\x33"
    assert EcuSimulator(spec).send(request) == expected.bytes
