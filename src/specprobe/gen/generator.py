from hashlib import sha256

from ..domain.schema import EcuSpec
from ..domain.testcase import TestCase
from ..rules.oracle import expected_response


def generate_suite(spec: EcuSpec) -> list[TestCase]:
    cases: dict[str, TestCase] = {}
    for did in spec.dids:
        for session in spec.sessions:
            for security in (0, 1):
                for write in (False, True):
                    if write and not did.write_sessions or not write and not did.read_sessions:
                        continue
                    sid = 0x2E if write else 0x22
                    payload = bytes(did.length_bytes) if write else b""
                    request = bytes([sid]) + did.did.to_bytes(2, "big") + payload
                    expected = expected_response(spec, session.id, security, {}, request).bytes
                    key = sha256(request + bytes([session.id, security])).hexdigest()[:16]
                    cases[key] = TestCase(
                        id=key,
                        trace_to=[],
                        preconditions={"session": session.id, "security": security},
                        steps=[request],
                        expected=expected,
                        tags=["write" if write else "read", did.name],
                    )
    return list(cases.values())
