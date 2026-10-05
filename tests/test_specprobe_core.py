from hypothesis import given, strategies as st

from specprobe.domain.schema import DataIdentifier, EcuSpec, SecurityLevel, Service, Session, Timing
from specprobe.gen.generator import generate_suite
from specprobe.rules.oracle import expected_response
from specprobe.sim.ecu import EcuSimulator
from specprobe.sim.transport import InMemoryTransport
from specprobe.runner.executor import run_suite


def sample_spec() -> EcuSpec:
    return EcuSpec(
        ecu_name="SYNTH-ECU", oem="OEM-A", version="1",
        sessions=[Session(id=1, name="default"), Session(id=3, name="extended")],
        security_levels=[SecurityLevel(level=0, name="locked"), SecurityLevel(level=1, name="level1")],
        services=[Service(sid=0x22, name="ReadDataByIdentifier"), Service(sid=0x2E, name="WriteDataByIdentifier")],
        dids=[DataIdentifier(did=0x1001, name="VehicleName", length_bytes=4, encoding="ascii", read_sessions=[1, 3], write_sessions=[3], write_security=1)],
        routines=[], timing=Timing(p2_ms=50, p2_star_ms=5000, s3_ms=5000),
        nrc_priority=[0x13, 0x12, 0x7F, 0x7E, 0x33, 0x31, 0x22],
    )


def test_clean_generated_suite_passes() -> None:
    spec = sample_spec()
    results = run_suite(generate_suite(spec), InMemoryTransport(EcuSimulator(spec)))
    assert results and all(result.passed for result in results)


@given(st.integers(min_value=0, max_value=1), st.integers(min_value=0, max_value=1))
def test_oracle_matches_clean_simulator(security: int, session: int) -> None:
    spec = sample_spec()
    request = b"\x22\x10\x01"
    ecu = EcuSimulator(spec)
    ecu.current_session = session + 1
    ecu.security_level = security
    actual = ecu.handle(request)
    expected = expected_response(spec, session + 1, security, {}, request).bytes
    assert actual == expected
