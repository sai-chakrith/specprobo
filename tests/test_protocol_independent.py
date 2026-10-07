from udsoncan import Response
from udsoncan.services import DiagnosticSessionControl

from specprobe.demo import build_spec
from specprobe.rules.oracle import State, step
from specprobe.sim.ecu import EcuSimulator


def test_session_response_decodes_with_independent_2020_interpreter():
    spec = build_spec()
    oracle, _ = step(spec, State(session=1), {}, b"\x10\x03")
    for payload in [oracle.bytes, EcuSimulator(spec).send(b"\x10\x03")]:
        decoded = DiagnosticSessionControl.interpret_response(
            Response.from_payload(payload), standard_version=2020
        )
        assert decoded.service_data.p2_server_max == 0.05
        assert decoded.service_data.p2_star_server_max == 5.0
