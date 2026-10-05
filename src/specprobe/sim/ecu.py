from ..domain.schema import EcuSpec
from ..rules.uds_constants import (
    NRC_SERVICE_NOT_SUPPORTED_IN_SESSION,
    SID_READ_DATA,
    SID_ROUTINE_CONTROL,
    SID_SESSION_CONTROL,
    SID_WRITE_DATA,
)


class EcuSimulator:
    """Stateful table-driven ECU; it intentionally does not call the oracle."""

    def __init__(self, spec: EcuSpec) -> None:
        self.spec = spec
        self.current_session = spec.sessions[0].id
        self.security_level = 0
        self.environment: dict[str, object] = {}
        self.did_store = {did.did: bytes(did.length_bytes) for did in spec.dids}
        self.mutations: set[str] = set()

    def handle(self, request: bytes) -> bytes | None:
        if not request:
            return b"\x7f\x00\x13"
        sid = request[0]
        if sid == SID_SESSION_CONTROL:
            return self._session(request)
        if sid == SID_READ_DATA:
            response = self._read(request)
        elif sid == SID_WRITE_DATA:
            response = self._write(request)
        elif sid == SID_ROUTINE_CONTROL:
            response = self._routine(request)
        else:
            service = self.spec.service(sid)
            if service is None:
                response = bytes([0x7F, sid, NRC_SERVICE_NOT_SUPPORTED_IN_SESSION])
            elif service.allowed_sessions and self.current_session not in service.allowed_sessions and "MISSING_SESSION_CHECK" in self.mutations:
                response = bytes([sid + 0x40]) + request[1:]
            elif service.allowed_sessions and self.current_session not in service.allowed_sessions:
                response = bytes([0x7F, sid, NRC_SERVICE_NOT_SUPPORTED_IN_SESSION])
            else:
                response = bytes([sid + 0x40]) + request[1:]
        if "WRONG_NRC" in self.mutations and response and response[0] == 0x7F:
            return response[:2] + bytes([0x31])
        return response

    def _session(self, request: bytes) -> bytes:
        if len(request) != 2:
            return b"\x7f\x10\x13"
        target = request[1]
        if target not in {item.id for item in self.spec.sessions}:
            return b"\x7f\x10\x31"
        self.current_session = target
        self.security_level = 0
        return bytes([0x50, target])

    def _read(self, request: bytes) -> bytes:
        if len(request) != 3:
            return b"\x7f\x22\x13"
        did = self.spec.did(int.from_bytes(request[1:], "big"))
        if did is None or did.read_sessions and self.current_session not in did.read_sessions:
            return b"\x7f\x22\x31"
        if did.read_security is not None and self.security_level < did.read_security:
            return b"\x7f\x22\x33"
        return b"\x62" + request[1:] + self.did_store[did.did]

    def _write(self, request: bytes) -> bytes:
        if len(request) < 3:
            return b"\x7f\x2e\x13"
        did = self.spec.did(int.from_bytes(request[1:3], "big"))
        if did is None or did.write_sessions and self.current_session not in did.write_sessions:
            return b"\x7f\x2e\x31"
        if did.write_security is not None and self.security_level < did.write_security:
            return b"\x7f\x2e\x33"
        payload = request[3:]
        if len(payload) != did.length_bytes:
            return b"\x7f\x2e\x13"
        self.did_store[did.did] = payload
        return b"\x6e" + request[1:3]

    def _routine(self, request: bytes) -> bytes:
        if len(request) < 4:
            return b"\x7f\x31\x13"
        routine = next((item for item in self.spec.routines if item.rid == int.from_bytes(request[2:4], "big")), None)
        if routine is None or self.current_session not in routine.sessions:
            return b"\x7f\x31\x31"
        return b"\x71" + request[1:4]
