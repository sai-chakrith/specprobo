from pydantic import BaseModel

from ..domain.testcase import TestCase
from ..sim.transport import Transport


class TestResult(BaseModel):
    test_id: str
    passed: bool
    expected: bytes | None
    actual: bytes | None


def run_suite(cases: list[TestCase], transport: Transport) -> list[TestResult]:
    results: list[TestResult] = []
    for case in cases:
        ecu = getattr(transport, "ecu", None)
        if ecu is not None:
            ecu.current_session = int(case.preconditions.get("session", ecu.current_session))
            ecu.security_level = int(case.preconditions.get("security", ecu.security_level))
        actual = transport.send(case.steps[0])
        results.append(TestResult(test_id=case.id, passed=actual == case.expected, expected=case.expected, actual=actual))
    return results
