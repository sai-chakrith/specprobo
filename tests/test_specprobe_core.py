from hypothesis import given, settings
from hypothesis import strategies as st

from specprobe.domain.schema import (
    DataIdentifier,
    EcuSpec,
    Precondition,
    Routine,
    SecurityLevel,
    Service,
    Session,
    Timing,
)
from specprobe.domain.testcase import TestCase as Case
from specprobe.domain.testcase import TraceRef
from specprobe.gen.generator import generate_suite
from specprobe.rules.oracle import State, expected_response, step
from specprobe.runner.executor import run_suite
from specprobe.sim.ecu import EcuSimulator
from specprobe.sim.mutations import MUTATION_DESCRIPTIONS, Mutation, MutationId, mutant_simulator
from specprobe.sim.transport import InMemoryTransport


def sample_spec() -> EcuSpec:
    return EcuSpec(
        ecu_name="SYNTH-ECU",
        oem="OEM-A",
        version="1",
        sessions=[Session(id=1, name="default"), Session(id=3, name="extended")],
        security_levels=[
            SecurityLevel(level=0, name="locked"),
            SecurityLevel(level=1, name="level1"),
        ],
        services=[
            Service(sid=0x10, name="SessionControl"),
            Service(sid=0x11, name="Reset"),
            Service(sid=0x22, name="ReadDataByIdentifier"),
            Service(sid=0x27, name="SecurityAccess"),
            Service(sid=0x2E, name="WriteDataByIdentifier"),
            Service(
                sid=0x31, name="RoutineControl", allowed_sessions=[3], required_security_level=1
            ),
            Service(sid=0x3E, name="TesterPresent", suppress_positive_response_supported=True),
        ],
        dids=[
            DataIdentifier(
                did=0x1001,
                name="VehicleName",
                length_bytes=4,
                encoding="ascii",
                read_sessions=[1, 3],
                write_sessions=[3],
                read_security=1,
                write_security=1,
                preconditions=[
                    Precondition(
                        kind="signal",
                        signal="vehicle_speed_kmh",
                        op="==",
                        value=0,
                        source_text="speed is zero",
                    )
                ],
            )
        ],
        routines=[
            Routine(
                rid=0x2001,
                name="Routine",
                control_types=[1, 2],
                sessions=[3],
                security=1,
                parameter_lengths={1: 1, 2: 0},
            )
        ],
        timing=Timing(p2_ms=50, p2_star_ms=5000, s3_ms=5000),
        nrc_priority=[0x13, 0x12, 0x11, 0x7F, 0x7E, 0x33, 0x35, 0x24, 0x31, 0x22],
    )


@settings(max_examples=500, derandomize=True)
@given(
    st.lists(
        st.sampled_from(
            [
                b"\x22\x10\x01",
                b"\x22\x10",
                b"\x2e\x10\x01\x00\x00\x00\x00\x00",
                b"\x27\x01",
                b"\x27\x02\xff\xff",
                b"\x31\x01\x20\x01\x00",
                b"\x3e\x80",
                b"\x10\x03",
                b"\x99",
            ]
        ),
        min_size=1,
        max_size=8,
    )
)
def test_oracle_matches_clean_simulator(requests: list[bytes]) -> None:
    spec = sample_spec()
    simulator = EcuSimulator(spec)
    state = State(session=1)
    for request in requests:
        expected, state = step(spec, state, {"vehicle_speed_kmh": 0}, request)
        assert simulator.send(request) == expected.bytes


def test_clean_generated_cases_use_transport_state() -> None:
    spec = sample_spec()
    request = b"\x22\x10\x01"
    expected = expected_response(spec, 1, 0, {}, request).bytes
    cases = [
        Case(
            id="read",
            trace_to=[TraceRef(field_id="dids[0].did", page=1)],
            steps=[request],
            expected=expected,
            preconditions={},
            tags=["read"],
        )
    ]
    results = run_suite(cases, InMemoryTransport(EcuSimulator(spec)))
    assert results[0].passed


def test_generated_case_expectations_match_oracle() -> None:
    spec = sample_spec()
    for case in generate_suite(spec):
        state = State(session=spec.sessions[0].id)
        for request in case.setup_steps:
            _, state = step(spec, state, case.environment, request)
        expected = None
        for request in case.steps:
            response, state = step(spec, state, case.environment, request)
            expected = response.bytes
        assert case.expected == expected, case.id


def _mutation_case(
    mutation_id: MutationId,
    request: bytes,
    setup: list[bytes] | None = None,
    env: dict[str, object] | None = None,
) -> tuple[bytes | None, bytes | None]:
    spec = sample_spec()
    clean = EcuSimulator(spec)
    mutant = mutant_simulator(
        spec, [Mutation(mutation_id, MUTATION_DESCRIPTIONS[mutation_id])]
    )
    for item in setup or []:
        clean.send(item)
        mutant.send(item)
    if mutation_id == MutationId.SECURITY_NOT_RELOCKED_ON_SESSION_CHANGE:
        clean.send(b"\x10\x01")
        mutant.send(b"\x10\x01")
    clean.set_environment(env or {})
    mutant.set_environment(env or {})
    return clean.send(request), mutant.send(request)


def test_each_mutation_changes_an_observable_result() -> None:
    cases = {
        MutationId.WRONG_NRC: (b"\x22\xff\xff", []),
        MutationId.MISSING_SESSION_CHECK: (b"\x31\x01\x20\x01\x00", []),
        MutationId.MISSING_SECURITY_CHECK_ON_WRITE: (
            b"\x2e\x10\x01\x00\x00\x00\x00",
            [b"\x10\x03"],
        ),
        MutationId.DID_LENGTH_OFF_BY_ONE: (
            b"\x2e\x10\x01\x00\x00\x00\x00\x00",
            [b"\x10\x03", b"\x27\x01", b"\x27\x02\xff\x5b"],
        ),
        MutationId.SUBFUNCTION_ACCEPTED_WHEN_UNSUPPORTED: (
            b"\x31\x7f\x20\x01",
            [b"\x10\x03", b"\x27\x01", b"\x27\x02\xff\x5b"],
        ),
        MutationId.WRONG_NRC_PRIORITY: (b"\x31\x01\x20\x01\x00", []),
        MutationId.SECURITY_NOT_RELOCKED_ON_SESSION_CHANGE: (
            b"\x22\x10\x01",
            [b"\x10\x03", b"\x27\x01", b"\x27\x02\xff\x5b"],
        ),
        MutationId.PRECONDITION_IGNORED: (
            b"\x2e\x10\x01\x00\x00\x00\x00",
            [b"\x10\x03", b"\x27\x01", b"\x27\x02\xff\x5b"],
        ),
    }
    for mutation_id, (request, setup) in cases.items():
        environment = (
            {"vehicle_speed_kmh": 0}
            if mutation_id == MutationId.DID_LENGTH_OFF_BY_ONE
            else {"vehicle_speed_kmh": 10}
        )
        clean, mutant = _mutation_case(mutation_id, request, setup, environment)
        assert clean != mutant, mutation_id
