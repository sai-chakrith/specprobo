from collections.abc import Iterable
from dataclasses import dataclass

from ..domain.schema import EcuSpec, Precondition
from .mutations import Mutation, MutationId, mutation_config
from .transport import Transport

SID_SESSION_CONTROL = 0x10
SID_ECU_RESET = 0x11
SID_READ_DATA = 0x22
SID_SECURITY_ACCESS = 0x27
SID_WRITE_DATA = 0x2E
SID_ROUTINE_CONTROL = 0x31
SID_TESTER_PRESENT = 0x3E

NRC_SERVICE_NOT_SUPPORTED = 0x11
NRC_SUBFUNCTION_NOT_SUPPORTED = 0x12
NRC_INCORRECT_LENGTH = 0x13
NRC_REQUEST_SEQUENCE_ERROR = 0x24
NRC_REQUEST_OUT_OF_RANGE = 0x31
NRC_SECURITY_ACCESS_DENIED = 0x33
NRC_INVALID_KEY = 0x35
NRC_CONDITIONS_NOT_CORRECT = 0x22
NRC_SERVICE_NOT_SUPPORTED_IN_SESSION = 0x7F
NRC_SUBFUNCTION_NOT_SUPPORTED_IN_SESSION = 0x7E


@dataclass(frozen=True)
class SimulatorState:
    session: int
    security_level: int = 0
    pending_security_level: int | None = None


def _seed(level: int) -> bytes:
    return bytes((0xA5, level & 0xFF))


def _key(seed: bytes) -> bytes:
    return bytes(value ^ 0x5A for value in seed)


class EcuSimulator(Transport):
    """Independent table-driven ECU implementation with constructor-configured mutants."""

    def __init__(self, spec: EcuSpec, mutations: Iterable[Mutation] = ()) -> None:
        self.spec = spec
        self.state = SimulatorState(session=spec.sessions[0].id)
        self.environment: dict[str, object] = {}
        self.did_store = {did.did: bytes(did.length_bytes) for did in spec.dids}
        self.mutations = mutation_config(list(mutations))

    def send(self, request: bytes) -> bytes | None:
        return self.handle(request)

    def set_environment(self, environment: dict[str, object]) -> None:
        self.environment = dict(environment)

    def handle(self, request: bytes) -> bytes | None:
        if not request:
            return self._finish(0, self._negative(0, NRC_INCORRECT_LENGTH))
        sid = request[0]
        response: bytes | None
        if sid == SID_SESSION_CONTROL:
            response = self._session(request)
        elif sid == SID_ECU_RESET:
            response = self._reset(request)
        elif sid == SID_SECURITY_ACCESS:
            response = self._security(request)
        elif sid == SID_READ_DATA:
            response = self._read(request)
        elif sid == SID_WRITE_DATA:
            response = self._write(request)
        elif sid == SID_ROUTINE_CONTROL:
            response = self._routine(request)
        elif sid == SID_TESTER_PRESENT:
            response = self._tester_present(request)
        else:
            response = self._negative(sid, NRC_SERVICE_NOT_SUPPORTED)
        return self._finish(sid, response)

    def _negative(self, sid: int, nrc: int) -> bytes:
        return bytes((0x7F, sid, nrc))

    def _finish(self, sid: int, response: bytes | None) -> bytes | None:
        if (
            response is not None
            and MutationId.WRONG_NRC in self.mutations
            and response[:1] == b"\x7f"
        ):
            nrc = response[2] if response[2] != 0x31 else 0x22
            return response[:2] + bytes((nrc,))
        return response

    def _service_allowed(self, sid: int, request: bytes) -> bytes | None:
        service = self.spec.service(sid)
        if service is None:
            return self._negative(sid, NRC_SERVICE_NOT_SUPPORTED)
        candidates: list[int] = []
        if (
            service.allowed_sessions
            and self.state.session not in service.allowed_sessions
            and MutationId.MISSING_SESSION_CHECK not in self.mutations
        ):
            candidates.append(NRC_SERVICE_NOT_SUPPORTED_IN_SESSION)
        if (
            service.required_security_level is not None
            and self.state.security_level < service.required_security_level
        ):
            candidates.append(NRC_SECURITY_ACCESS_DENIED)
        if service.subfunctions and len(request) > 1:
            subfunction = request[1] & 0x7F
            entry = next((item for item in service.subfunctions if item.value == subfunction), None)
            if entry is None:
                if MutationId.SUBFUNCTION_ACCEPTED_WHEN_UNSUPPORTED not in self.mutations:
                    candidates.append(NRC_SUBFUNCTION_NOT_SUPPORTED)
            elif (
                entry.allowed_sessions
                and self.state.session not in entry.allowed_sessions
                and MutationId.MISSING_SESSION_CHECK not in self.mutations
            ):
                candidates.append(NRC_SUBFUNCTION_NOT_SUPPORTED_IN_SESSION)
            elif (
                entry.required_security_level is not None
                and self.state.security_level < entry.required_security_level
            ):
                candidates.append(NRC_SECURITY_ACCESS_DENIED)
        if not candidates:
            return None
        if MutationId.WRONG_NRC_PRIORITY in self.mutations:
            return self._negative(sid, min(candidates))
        return self._negative(sid, candidates[0])

    def _session(self, request: bytes) -> bytes:
        blocked = self._service_allowed(SID_SESSION_CONTROL, request)
        if blocked:
            return blocked
        if len(request) != 2:
            return self._negative(SID_SESSION_CONTROL, NRC_INCORRECT_LENGTH)
        target = request[1]
        if not any(item.id == target for item in self.spec.sessions):
            return self._negative(SID_SESSION_CONTROL, NRC_REQUEST_OUT_OF_RANGE)
        security = (
            self.state.security_level
            if MutationId.SECURITY_NOT_RELOCKED_ON_SESSION_CHANGE in self.mutations
            else 0
        )
        self.state = SimulatorState(target, security)
        return bytes((0x50, target))

    def _reset(self, request: bytes) -> bytes:
        blocked = self._service_allowed(SID_ECU_RESET, request)
        if blocked:
            return blocked
        if len(request) != 2:
            return self._negative(SID_ECU_RESET, NRC_INCORRECT_LENGTH)
        self.state = SimulatorState(self.state.session)
        return bytes((0x51, request[1] & 0x7F))

    def _security(self, request: bytes) -> bytes:
        blocked = self._service_allowed(SID_SECURITY_ACCESS, request)
        if blocked:
            return blocked
        if len(request) < 2:
            return self._negative(SID_SECURITY_ACCESS, NRC_INCORRECT_LENGTH)
        subfunction = request[1]
        level = (subfunction + 1) // 2
        if level <= 0 or level > max((item.level for item in self.spec.security_levels), default=0):
            return self._negative(SID_SECURITY_ACCESS, NRC_REQUEST_OUT_OF_RANGE)
        if subfunction % 2:
            if len(request) != 2:
                return self._negative(SID_SECURITY_ACCESS, NRC_INCORRECT_LENGTH)
            self.state = SimulatorState(self.state.session, self.state.security_level, level)
            return bytes((0x67, subfunction)) + _seed(level)
        if len(request) != 4 or self.state.pending_security_level != level:
            return self._negative(SID_SECURITY_ACCESS, NRC_REQUEST_SEQUENCE_ERROR)
        if request[2:] != _key(_seed(level)):
            return self._negative(SID_SECURITY_ACCESS, NRC_INVALID_KEY)
        self.state = SimulatorState(self.state.session, level)
        return bytes((0x67, subfunction))

    def _read(self, request: bytes) -> bytes:
        blocked = self._service_allowed(SID_READ_DATA, request)
        if blocked:
            return blocked
        if len(request) != 3:
            return self._negative(SID_READ_DATA, NRC_INCORRECT_LENGTH)
        did = self.spec.did(int.from_bytes(request[1:3], "big"))
        if did is None or (
            did.read_sessions
            and self.state.session not in did.read_sessions
            and MutationId.MISSING_SESSION_CHECK not in self.mutations
        ):
            return self._negative(SID_READ_DATA, NRC_REQUEST_OUT_OF_RANGE)
        if did.read_security is not None and self.state.security_level < did.read_security:
            return self._negative(SID_READ_DATA, NRC_SECURITY_ACCESS_DENIED)
        return b"\x62" + request[1:3] + self.did_store[did.did]

    def _write(self, request: bytes) -> bytes:
        blocked = self._service_allowed(SID_WRITE_DATA, request)
        if blocked:
            return blocked
        if len(request) < 3:
            return self._negative(SID_WRITE_DATA, NRC_INCORRECT_LENGTH)
        did = self.spec.did(int.from_bytes(request[1:3], "big"))
        if did is None or (
            did.write_sessions
            and self.state.session not in did.write_sessions
            and MutationId.MISSING_SESSION_CHECK not in self.mutations
        ):
            return self._negative(SID_WRITE_DATA, NRC_REQUEST_OUT_OF_RANGE)
        if (
            did.write_security is not None
            and self.state.security_level < did.write_security
            and MutationId.MISSING_SECURITY_CHECK_ON_WRITE not in self.mutations
        ):
            return self._negative(SID_WRITE_DATA, NRC_SECURITY_ACCESS_DENIED)
        payload = request[3:]
        allowed_lengths = (
            {did.length_bytes, did.length_bytes + 1}
            if MutationId.DID_LENGTH_OFF_BY_ONE in self.mutations
            else {did.length_bytes}
        )
        if len(payload) not in allowed_lengths:
            return self._negative(SID_WRITE_DATA, NRC_INCORRECT_LENGTH)
        if MutationId.PRECONDITION_IGNORED not in self.mutations and not self._conditions_hold(
            did.preconditions
        ):
            return self._negative(SID_WRITE_DATA, NRC_CONDITIONS_NOT_CORRECT)
        self.did_store[did.did] = payload[: did.length_bytes]
        return b"\x6e" + request[1:3]

    def _routine(self, request: bytes) -> bytes:
        blocked = self._service_allowed(SID_ROUTINE_CONTROL, request)
        if blocked:
            return blocked
        if len(request) < 4:
            return self._negative(SID_ROUTINE_CONTROL, NRC_INCORRECT_LENGTH)
        control = request[1] & 0x7F
        routine = self.spec.routine(int.from_bytes(request[2:4], "big"))
        if routine is None:
            return self._negative(SID_ROUTINE_CONTROL, NRC_REQUEST_OUT_OF_RANGE)
        if control not in routine.control_types:
            if MutationId.SUBFUNCTION_ACCEPTED_WHEN_UNSUPPORTED in self.mutations:
                control = routine.control_types[0] if routine.control_types else control
            else:
                return self._negative(SID_ROUTINE_CONTROL, NRC_SUBFUNCTION_NOT_SUPPORTED)
        if (
            routine.sessions
            and self.state.session not in routine.sessions
            and MutationId.MISSING_SESSION_CHECK not in self.mutations
        ):
            return self._negative(SID_ROUTINE_CONTROL, NRC_SUBFUNCTION_NOT_SUPPORTED_IN_SESSION)
        if routine.security is not None and self.state.security_level < routine.security:
            return self._negative(SID_ROUTINE_CONTROL, NRC_SECURITY_ACCESS_DENIED)
        if len(request[4:]) != routine.parameter_lengths.get(control, 0):
            return self._negative(SID_ROUTINE_CONTROL, NRC_INCORRECT_LENGTH)
        if MutationId.PRECONDITION_IGNORED not in self.mutations and not self._conditions_hold(
            routine.preconditions
        ):
            return self._negative(SID_ROUTINE_CONTROL, NRC_CONDITIONS_NOT_CORRECT)
        return bytes((0x71, request[1])) + request[2:4]

    def _tester_present(self, request: bytes) -> bytes | None:
        blocked = self._service_allowed(SID_TESTER_PRESENT, request)
        if blocked:
            return blocked
        if len(request) not in {1, 2}:
            return self._negative(SID_TESTER_PRESENT, NRC_INCORRECT_LENGTH)
        subfunction = request[1] if len(request) == 2 else 0
        if subfunction & 0x7F:
            if MutationId.SUBFUNCTION_ACCEPTED_WHEN_UNSUPPORTED in self.mutations:
                return bytes((0x7E, subfunction & 0x7F))
            return self._negative(SID_TESTER_PRESENT, NRC_SUBFUNCTION_NOT_SUPPORTED)
        if subfunction & 0x80:
            return None
        return b"\x7e\x00"

    def _conditions_hold(self, conditions: list[Precondition]) -> bool:
        for condition in conditions:
            actual: object = (
                self.state.session
                if condition.kind == "session"
                else self.state.security_level
                if condition.kind == "security"
                else self.environment.get(condition.signal or "")
            )
            expected = condition.value
            if (
                condition.op == "=="
                and actual != expected
                or condition.op == "!="
                and actual == expected
            ):
                return False
            if condition.op in {"<", "<=", ">", ">="}:
                if not isinstance(actual, (int, float)) or not isinstance(expected, (int, float)):
                    return False
                if (
                    condition.op == "<"
                    and not actual < expected
                    or condition.op == "<="
                    and not actual <= expected
                    or condition.op == ">"
                    and not actual > expected
                    or condition.op == ">="
                    and not actual >= expected
                ):
                    return False
        return True
