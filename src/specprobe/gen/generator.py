from collections.abc import Iterable
from hashlib import sha256

from ..domain.provenance import APPROVED_STATUSES
from ..domain.schema import EcuSpec, Precondition
from ..domain.testcase import TestCase, TraceRef
from ..rules.oracle import State, security_key, step


def _trace(spec: EcuSpec, paths: Iterable[str], statuses: frozenset[str]) -> list[TraceRef]:
    result: list[TraceRef] = []
    for path in paths:
        provenance = spec.field_registry.get(path)
        if provenance is not None and provenance.status not in statuses:
            return []
        result.append(
            TraceRef(
                field_id=provenance.field_id if provenance else path,
                page=provenance.page if provenance and provenance.page is not None else 0,
            )
        )
    return result


def _environment(conditions: list[Precondition], truth: bool) -> dict[str, object]:
    values: dict[str, object] = {}
    for condition in conditions:
        if condition.signal is None:
            continue
        value = condition.value
        if truth:
            values[condition.signal] = value
        elif isinstance(value, bool):
            values[condition.signal] = not value
        elif isinstance(value, (int, float)):
            values[condition.signal] = value + 1
        else:
            values[condition.signal] = "__false__"
    return values


def _setup(spec: EcuSpec, session: int, security: int) -> list[bytes]:
    steps: list[bytes] = [bytes((0x10, spec.sessions[0].id))]
    if session != spec.sessions[0].id:
        steps.append(bytes((0x10, session)))
    if security > 0:
        seed = bytes((0xA5, security))
        steps.extend(
            (bytes((0x27, security * 2 - 1)), bytes((0x27, security * 2)) + security_key(seed))
        )
    return steps


def _make_case(
    spec: EcuSpec,
    name: str,
    setup: list[bytes],
    steps: list[bytes],
    env: dict[str, object],
    traces: list[str],
    statuses: frozenset[str],
) -> TestCase | None:
    trace_to = _trace(spec, traces, statuses)
    if not trace_to:
        return None
    state = State(session=spec.sessions[0].id)
    for request in setup:
        _, state = step(spec, state, env, request)
    expected = None
    for request in steps:
        response, state = step(spec, state, env, request)
        expected = response.bytes
    digest = sha256((name + repr(setup) + repr(steps) + repr(env)).encode()).hexdigest()[:16]
    return TestCase(
        id=digest,
        trace_to=trace_to,
        preconditions={"session": state.session, "security": state.security_level},
        setup_steps=setup,
        steps=steps,
        environment=env,
        expected=expected,
        tags=[name],
    )


def generate_suite(spec: EcuSpec, statuses: frozenset[str] = APPROVED_STATUSES) -> list[TestCase]:
    cases: dict[str, TestCase] = {}
    max_security = max((item.level for item in spec.security_levels), default=0)
    security_states = sorted({0, max_security})
    for index, did in enumerate(spec.dids):
        paths = [f"dids[{index}].did", f"dids[{index}].length_bytes"]
        for session in spec.sessions:
            for security in security_states:
                if did.read_sessions:
                    request = bytes((0x22,)) + did.did.to_bytes(2, "big")
                    case = _make_case(
                        spec,
                        f"did-read-{did.did:x}-{session.id}-{security}",
                        _setup(spec, session.id, security),
                        [request],
                        {},
                        paths,
                        statuses,
                    )
                    if case:
                        cases[case.id] = case
                    unknown = _make_case(
                        spec, f"did-unknown-{did.did:x}", [], [b"\x22\xff\xff"], {}, paths, statuses
                    )
                    if unknown:
                        cases[unknown.id] = unknown
                    bad_sessions = [
                        item.id for item in spec.sessions if item.id not in did.read_sessions
                    ]
                    if bad_sessions:
                        case = _make_case(
                            spec,
                            f"did-wrong-session-{did.did:x}",
                            _setup(spec, bad_sessions[0], 0),
                            [request],
                            {},
                            paths,
                            statuses,
                        )
                        if case:
                            cases[case.id] = case
                    if did.read_security is not None:
                        case = _make_case(
                            spec,
                            f"did-missing-security-{did.did:x}",
                            _setup(spec, did.read_sessions[0], 0),
                            [request],
                            {},
                            paths,
                            statuses,
                        )
                        if case:
                            cases[case.id] = case
                if did.write_sessions:
                    for length in (
                        max(0, did.length_bytes - 1),
                        did.length_bytes,
                        did.length_bytes + 1,
                    ):
                        request = bytes((0x2E,)) + did.did.to_bytes(2, "big") + bytes(length)
                        case = _make_case(
                            spec,
                            f"did-write-{did.did:x}-{session.id}-{security}-{length}",
                            _setup(spec, session.id, security),
                            [request],
                            {},
                            paths,
                            statuses,
                        )
                        if case:
                            cases[case.id] = case
                    if did.preconditions:
                        for truth in (True, False, None):
                            request = (
                                bytes((0x2E,))
                                + did.did.to_bytes(2, "big")
                                + bytes(did.length_bytes)
                            )
                            case = _make_case(
                                spec,
                                f"did-precondition-{did.did:x}-{truth}",
                                _setup(spec, session.id, security),
                                [request],
                                (
                                    _environment(did.preconditions, truth is True)
                                    if truth is not None
                                    else {}
                                ),
                                paths,
                                statuses,
                            )
                            if case:
                                cases[case.id] = case
                    if did.read_security is not None and len(did.read_sessions) > 1:
                        unlocked = _setup(spec, did.read_sessions[-1], did.read_security)
                        relock_steps = [
                            bytes((0x10, did.read_sessions[0])),
                            bytes((0x22,)) + did.did.to_bytes(2, "big"),
                        ]
                        case = _make_case(
                            spec,
                            f"security-relock-{did.did:x}",
                            unlocked,
                            relock_steps,
                            {},
                            paths,
                            statuses,
                        )
                        if case:
                            cases[case.id] = case
    for index, service in enumerate(spec.services):
        service_path = f"services[{index}].subfunctions"
        nominal_length = {
            0x10: 2,
            0x11: 2,
            0x27: 2,
            0x22: 3,
            0x2E: 3 + max((item.length_bytes for item in spec.dids), default=1),
            0x31: 4
            + max(
                (max(item.parameter_lengths.values(), default=0) for item in spec.routines),
                default=0,
            ),
            0x3E: 2,
        }.get(service.sid, 1)
        service_requests = [
            b"" if length == 0 else bytes((service.sid,)) + bytes(length - 1)
            for length in range(nominal_length + 3)
        ]
        if service.subfunctions:
            service_requests.extend(
                bytes((service.sid, value)) + bytes(max(0, nominal_length - 2))
                for value in range(256)
            )
        for session in spec.sessions:
            for security in sorted({0, max_security}):
                for request_index, request in enumerate(service_requests):
                    case = _make_case(
                        spec,
                        f"service-{service.sid:x}-{session.id}-{security}-{request_index}",
                        _setup(spec, session.id, security),
                        [request],
                        {},
                        [service_path],
                        statuses,
                    )
                    if case:
                        cases[case.id] = case
        if service.subfunctions:
            case = _make_case(
                spec,
                f"invalid-subfunction-{service.sid:x}",
                [],
                [bytes((service.sid, 0x7F))],
                {},
                [service_path],
                statuses,
            )
            if case:
                cases[case.id] = case
        if service.sid == 0x3E and service.suppress_positive_response_supported:
            case = _make_case(
                spec,
                "tester-present-spr",
                [],
                [b"\x3e\x80"],
                {},
                [f"services[{index}].suppress_positive_response_supported"],
                statuses,
            )
            if case:
                cases[case.id] = case
    unsupported = _make_case(
        spec, "unsupported-sid", [], [b"\x99"], {}, ["rules.unsupported_sid"], statuses
    )
    if unsupported:
        cases[unsupported.id] = unsupported
    for index, routine in enumerate(spec.routines):
        for control in routine.control_types:
            length = routine.parameter_lengths.get(control, 0)
            request = bytes((0x31, control)) + routine.rid.to_bytes(2, "big") + bytes(length)
            routine_session = routine.sessions[0] if routine.sessions else spec.sessions[0].id
            case = _make_case(
                spec,
                f"routine-{routine.rid:x}-{control}",
                _setup(spec, routine_session, routine.security or 0),
                [request],
                {},
                [f"routines[{index}].rid", f"routines[{index}].parameter_lengths"],
                statuses,
            )
            if case:
                cases[case.id] = case
        invalid_control = 0x7F
        invalid_request = bytes((0x31, invalid_control)) + routine.rid.to_bytes(2, "big")
        routine_session = routine.sessions[0] if routine.sessions else spec.sessions[0].id
        case = _make_case(
            spec,
            f"routine-invalid-control-{routine.rid:x}",
            _setup(spec, routine_session, routine.security or 0),
            [invalid_request],
            {},
            [f"routines[{index}].control_types"],
            statuses,
        )
        if case:
            cases[case.id] = case
        collision_request = bytes(
            (0x31, routine.control_types[0] if routine.control_types else 1)
        ) + routine.rid.to_bytes(2, "big")
        collision = _make_case(
            spec,
            f"routine-nrc-priority-{routine.rid:x}",
            _setup(spec, spec.sessions[0].id, 0),
            [collision_request],
            {},
            [f"routines[{index}].sessions", f"routines[{index}].security"],
            statuses,
        )
        if collision:
            cases[collision.id] = collision
        if routine.preconditions:
            for truth in (True, False, None):
                case = _make_case(
                    spec,
                    f"routine-precondition-{routine.rid:x}-{truth}",
                    _setup(
                        spec,
                        routine.sessions[0] if routine.sessions else spec.sessions[0].id,
                        routine.security or 0,
                    ),
                    [
                        bytes((0x31, routine.control_types[0] if routine.control_types else 1))
                        + routine.rid.to_bytes(2, "big")
                        + bytes(routine.parameter_lengths.get(routine.control_types[0], 0))
                    ],
                    _environment(routine.preconditions, truth is True) if truth is not None else {},
                    [f"routines[{index}].preconditions"],
                    statuses,
                )
                if case:
                    cases[case.id] = case
    return list(cases.values())
