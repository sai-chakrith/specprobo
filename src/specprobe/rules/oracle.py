from dataclasses import dataclass

from ..domain.schema import EcuSpec
from .priority import choose_nrc
from .uds_constants import (
    NRC_CONDITIONS_NOT_CORRECT,
    NRC_INCORRECT_LENGTH,
    NRC_REQUEST_OUT_OF_RANGE,
    NRC_SECURITY_ACCESS_DENIED,
    NRC_SERVICE_NOT_SUPPORTED_IN_SESSION,
    positive_sid,
    SID_READ_DATA,
    SID_ROUTINE_CONTROL,
    SID_SESSION_CONTROL,
    SID_WRITE_DATA,
)
from .validators import validate_request


@dataclass(frozen=True)
class ExpectedResponse:
    positive: bytes | None = None
    nrc: int | None = None
    no_response: bool = False

    @property
    def bytes(self) -> bytes | None:
        if self.no_response or self.positive is None:
            return None
        return self.positive if self.nrc is None else bytes([0x7F, self.positive[0], self.nrc])


def expected_response(
    spec: EcuSpec,
    session: int,
    security_state: int,
    env: dict[str, object],
    request_bytes: bytes,
) -> ExpectedResponse:
    if not request_bytes:
        return ExpectedResponse(nrc=NRC_INCORRECT_LENGTH, positive=b"\x00")
    sid = request_bytes[0]
    service = spec.service(sid)
    if service is None:
        return ExpectedResponse(nrc=NRC_SERVICE_NOT_SUPPORTED_IN_SESSION, positive=bytes([sid]))
    candidates = validate_request(service, request_bytes)
    if service.allowed_sessions and session not in service.allowed_sessions:
        candidates.add(NRC_SERVICE_NOT_SUPPORTED_IN_SESSION)
    if service.required_security_level is not None and security_state < service.required_security_level:
        candidates.add(NRC_SECURITY_ACCESS_DENIED)
    if candidates:
        nrc = choose_nrc(candidates, spec.nrc_priority)
        return ExpectedResponse(nrc=nrc, positive=bytes([sid]))

    if sid == SID_SESSION_CONTROL:
        if len(request_bytes) != 2:
            return ExpectedResponse(nrc=NRC_INCORRECT_LENGTH, positive=bytes([sid]))
        return ExpectedResponse(positive=bytes([positive_sid(sid), request_bytes[1]]))
    if sid == SID_READ_DATA:
        if len(request_bytes) != 3:
            return ExpectedResponse(nrc=NRC_INCORRECT_LENGTH, positive=bytes([sid]))
        did = spec.did(int.from_bytes(request_bytes[1:3], "big"))
        if did is None or (did.read_sessions and session not in did.read_sessions):
            return ExpectedResponse(nrc=NRC_REQUEST_OUT_OF_RANGE, positive=bytes([sid]))
        if did.read_security is not None and security_state < did.read_security:
            return ExpectedResponse(nrc=NRC_SECURITY_ACCESS_DENIED, positive=bytes([sid]))
        return ExpectedResponse(positive=bytes([positive_sid(sid)]) + request_bytes[1:3] + bytes(did.length_bytes))
    if sid == SID_WRITE_DATA:
        if len(request_bytes) < 3:
            return ExpectedResponse(nrc=NRC_INCORRECT_LENGTH, positive=bytes([sid]))
        did = spec.did(int.from_bytes(request_bytes[1:3], "big"))
        if did is None or (did.write_sessions and session not in did.write_sessions):
            return ExpectedResponse(nrc=NRC_REQUEST_OUT_OF_RANGE, positive=bytes([sid]))
        if did.write_security is not None and security_state < did.write_security:
            return ExpectedResponse(nrc=NRC_SECURITY_ACCESS_DENIED, positive=bytes([sid]))
        if len(request_bytes[3:]) != did.length_bytes:
            return ExpectedResponse(nrc=NRC_INCORRECT_LENGTH, positive=bytes([sid]))
        if not _preconditions_hold(did.preconditions, session, security_state, env):
            return ExpectedResponse(nrc=NRC_CONDITIONS_NOT_CORRECT, positive=bytes([sid]))
        return ExpectedResponse(positive=bytes([positive_sid(sid)]) + request_bytes[1:3])
    if sid == SID_ROUTINE_CONTROL:
        if len(request_bytes) < 4:
            return ExpectedResponse(nrc=NRC_INCORRECT_LENGTH, positive=bytes([sid]))
        return ExpectedResponse(positive=bytes([positive_sid(sid)]) + request_bytes[1:4])
    return ExpectedResponse(positive=bytes([positive_sid(sid)]) + request_bytes[1:])


def _preconditions_hold(preconditions: list[object], session: int, security: int, env: dict[str, object]) -> bool:
    for condition in preconditions:
        kind = getattr(condition, "kind")
        actual: object = session if kind == "session" else security if kind == "security" else env.get(getattr(condition, "signal"))
        expected = getattr(condition, "value")
        op = getattr(condition, "op")
        if op == "==" and actual != expected or op == "!=" and actual == expected:
            return False
        comparisons = {"<": lambda: actual < expected, "<=": lambda: actual <= expected,
                       ">": lambda: actual > expected, ">=": lambda: actual >= expected}
        if op in comparisons and not comparisons[op]():
            return False
    return True
