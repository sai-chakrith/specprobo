from collections.abc import Callable
from dataclasses import dataclass, replace

from ..domain.schema import EcuSpec, Precondition
from .priority import choose_nrc
from .uds_constants import (
    NRC_CONDITIONS_NOT_CORRECT,
    NRC_INCORRECT_LENGTH,
    NRC_INVALID_KEY,
    NRC_REQUEST_OUT_OF_RANGE,
    NRC_REQUEST_SEQUENCE_ERROR,
    NRC_SECURITY_ACCESS_DENIED,
    NRC_SERVICE_NOT_SUPPORTED,
    NRC_SERVICE_NOT_SUPPORTED_IN_SESSION,
    NRC_SUBFUNCTION_NOT_SUPPORTED,
    NRC_SUBFUNCTION_NOT_SUPPORTED_IN_SESSION,
    SID_ECU_RESET,
    SID_READ_DATA,
    SID_ROUTINE_CONTROL,
    SID_SECURITY_ACCESS,
    SID_SESSION_CONTROL,
    SID_TESTER_PRESENT,
    SID_WRITE_DATA,
    positive_sid,
)


@dataclass(frozen=True)
class State:
    session: int
    security_level: int = 0
    pending_security_level: int | None = None


@dataclass(frozen=True)
class ExpectedResponse:
    positive: bytes | None = None
    nrc: int | None = None
    no_response: bool = False

    @property
    def bytes(self) -> bytes | None:
        if self.no_response:
            return None
        if self.nrc is not None:
            if self.positive is None:
                return None
            return bytes((0x7F, self.positive[0], self.nrc))
        return self.positive


def _negative(sid: int, nrc: int) -> ExpectedResponse:
    return ExpectedResponse(positive=bytes((sid,)), nrc=nrc)


def _choose(spec: EcuSpec, sid: int, candidates: set[int]) -> ExpectedResponse:
    selected = choose_nrc(candidates, spec.nrc_priority)
    return _negative(sid, selected if selected is not None else min(candidates))


def _seed(level: int) -> bytes:
    return bytes((0xA5, level & 0xFF))


def security_key(seed: bytes) -> bytes:
    return bytes(value ^ 0x5A for value in seed)


def _condition_holds(condition: Precondition, state: State, env: dict[str, object]) -> bool:
    if condition.kind == "session":
        actual: object = state.session
    elif condition.kind == "security":
        actual = state.security_level
    else:
        actual = env.get(condition.signal or "")
    expected = condition.value
    if condition.op == "==":
        return actual == expected
    if condition.op == "!=":
        return actual != expected
    if not isinstance(actual, (int, float)) or not isinstance(expected, (int, float)):
        return False
    comparisons: dict[str, Callable[[], bool]] = {
        "<": lambda: actual < expected,
        "<=": lambda: actual <= expected,
        ">": lambda: actual > expected,
        ">=": lambda: actual >= expected,
    }
    comparison = comparisons.get(condition.op or "")
    return comparison is not None and comparison()


def _conditions_hold(conditions: list[Precondition], state: State, env: dict[str, object]) -> bool:
    return all(_condition_holds(condition, state, env) for condition in conditions)


def _service_nrcs(spec: EcuSpec, state: State, sid: int, request: bytes) -> set[int]:
    service = spec.service(sid)
    if service is None:
        return {NRC_SERVICE_NOT_SUPPORTED}
    candidates: set[int] = set()
    if service.allowed_sessions and state.session not in service.allowed_sessions:
        candidates.add(NRC_SERVICE_NOT_SUPPORTED_IN_SESSION)
    if len(request) > 1 and service.subfunctions:
        subfunction = request[1] & 0x7F
        entry = next((item for item in service.subfunctions if item.value == subfunction), None)
        if entry is None:
            candidates.add(NRC_SUBFUNCTION_NOT_SUPPORTED)
        elif entry.allowed_sessions and state.session not in entry.allowed_sessions:
            candidates.add(NRC_SUBFUNCTION_NOT_SUPPORTED_IN_SESSION)
        elif (
            entry.required_security_level is not None
            and state.security_level < entry.required_security_level
        ):
            candidates.add(NRC_SECURITY_ACCESS_DENIED)
    if (
        service.required_security_level is not None
        and state.security_level < service.required_security_level
    ):
        candidates.add(NRC_SECURITY_ACCESS_DENIED)
    return candidates


def step(
    spec: EcuSpec, state: State, env: dict[str, object], request: bytes
) -> tuple[ExpectedResponse, State]:
    if not request:
        return _negative(0, NRC_INCORRECT_LENGTH), state
    sid = request[0]
    if spec.service(sid) is None:
        return _negative(sid, NRC_SERVICE_NOT_SUPPORTED), state
    candidates = _service_nrcs(spec, state, sid, request)
    if candidates:
        return _choose(spec, sid, candidates), state
    if sid == SID_SESSION_CONTROL:
        if len(request) != 2:
            return _choose(spec, sid, {NRC_INCORRECT_LENGTH}), state
        target = request[1]
        if spec.sessions and not any(item.id == target for item in spec.sessions):
            return _choose(spec, sid, {NRC_REQUEST_OUT_OF_RANGE}), state
        new_state = replace(state, session=target, security_level=0, pending_security_level=None)
        return ExpectedResponse(positive=bytes((positive_sid(sid), target))), new_state
    if sid == SID_SECURITY_ACCESS:
        if len(request) < 2:
            return _choose(spec, sid, {NRC_INCORRECT_LENGTH}), state
        subfunction = request[1]
        level = (subfunction + 1) // 2
        if level <= 0 or level > max((item.level for item in spec.security_levels), default=0):
            return _choose(spec, sid, {NRC_REQUEST_OUT_OF_RANGE}), state
        if subfunction % 2:
            if len(request) != 2:
                return _choose(spec, sid, {NRC_INCORRECT_LENGTH}), state
            return ExpectedResponse(
                positive=bytes((positive_sid(sid), subfunction)) + _seed(level)
            ), replace(state, pending_security_level=level)
        if len(request) != 4:
            return _choose(spec, sid, {NRC_INCORRECT_LENGTH}), state
        if state.pending_security_level != level:
            return _choose(spec, sid, {NRC_REQUEST_SEQUENCE_ERROR}), state
        if request[2:] != security_key(_seed(level)):
            return _choose(spec, sid, {NRC_INVALID_KEY}), state
        return ExpectedResponse(positive=bytes((positive_sid(sid), subfunction))), replace(
            state, security_level=level, pending_security_level=None
        )
    if sid == SID_READ_DATA:
        if len(request) != 3:
            return _choose(spec, sid, {NRC_INCORRECT_LENGTH}), state
        did = spec.did(int.from_bytes(request[1:3], "big"))
        if did is None or did.read_sessions and state.session not in did.read_sessions:
            return _choose(spec, sid, {NRC_REQUEST_OUT_OF_RANGE}), state
        if did.read_security is not None and state.security_level < did.read_security:
            return _choose(spec, sid, {NRC_SECURITY_ACCESS_DENIED}), state
        return ExpectedResponse(
            positive=bytes((positive_sid(sid),)) + request[1:3] + bytes(did.length_bytes)
        ), state
    if sid == SID_WRITE_DATA:
        if len(request) < 3:
            return _choose(spec, sid, {NRC_INCORRECT_LENGTH}), state
        did = spec.did(int.from_bytes(request[1:3], "big"))
        if did is None or did.write_sessions and state.session not in did.write_sessions:
            return _choose(spec, sid, {NRC_REQUEST_OUT_OF_RANGE}), state
        if did.write_security is not None and state.security_level < did.write_security:
            return _choose(spec, sid, {NRC_SECURITY_ACCESS_DENIED}), state
        if len(request[3:]) != did.length_bytes:
            return _choose(spec, sid, {NRC_INCORRECT_LENGTH}), state
        if not _conditions_hold(did.preconditions, state, env):
            return _choose(spec, sid, {NRC_CONDITIONS_NOT_CORRECT}), state
        return ExpectedResponse(positive=bytes((positive_sid(sid),)) + request[1:3]), state
    if sid == SID_ROUTINE_CONTROL:
        if len(request) < 4:
            return _choose(spec, sid, {NRC_INCORRECT_LENGTH}), state
        control = request[1] & 0x7F
        routine = spec.routine(int.from_bytes(request[2:4], "big"))
        if routine is None:
            return _choose(spec, sid, {NRC_REQUEST_OUT_OF_RANGE}), state
        if control not in routine.control_types:
            return _choose(spec, sid, {NRC_SUBFUNCTION_NOT_SUPPORTED}), state
        if routine.sessions and state.session not in routine.sessions:
            return _choose(spec, sid, {NRC_SUBFUNCTION_NOT_SUPPORTED_IN_SESSION}), state
        if routine.security is not None and state.security_level < routine.security:
            return _choose(spec, sid, {NRC_SECURITY_ACCESS_DENIED}), state
        if len(request[4:]) != routine.parameter_lengths.get(control, 0):
            return _choose(spec, sid, {NRC_INCORRECT_LENGTH}), state
        if not _conditions_hold(routine.preconditions, state, env):
            return _choose(spec, sid, {NRC_CONDITIONS_NOT_CORRECT}), state
        return ExpectedResponse(
            positive=bytes((positive_sid(sid), request[1])) + request[2:4]
        ), state
    if sid == SID_TESTER_PRESENT:
        if len(request) not in {1, 2}:
            return _choose(spec, sid, {NRC_INCORRECT_LENGTH}), state
        subfunction = request[1] if len(request) == 2 else 0
        if subfunction & 0x7F:
            return _choose(spec, sid, {NRC_SUBFUNCTION_NOT_SUPPORTED}), state
        if subfunction & 0x80:
            return ExpectedResponse(no_response=True), state
        return ExpectedResponse(positive=bytes((positive_sid(sid), 0))), state
    if sid == SID_ECU_RESET:
        if len(request) != 2:
            return _choose(spec, sid, {NRC_INCORRECT_LENGTH}), state
        return ExpectedResponse(positive=bytes((positive_sid(sid), request[1] & 0x7F))), replace(
            state, security_level=0, pending_security_level=None
        )
    return ExpectedResponse(positive=bytes((positive_sid(sid),)) + request[1:]), state


def expected_response(
    spec: EcuSpec, session: int, security_state: int, env: dict[str, object], request_bytes: bytes
) -> ExpectedResponse:
    response, _ = step(
        spec, State(session=session, security_level=security_state), env, request_bytes
    )
    return response
