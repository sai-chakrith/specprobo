from pydantic import BaseModel

from ..domain.testcase import TestCase
from ..sim.transport import Transport


class TestResult(BaseModel):
    test_id: str
    passed: bool
    expected: bytes | None
    actual: bytes | None
    trace_to: list[object]


def run_suite(cases: list[TestCase], transport: Transport) -> list[TestResult]:
    results: list[TestResult] = []
    for case in cases:
        transport.set_environment(case.environment)
        for request in case.setup_steps:
            transport.send(request)
        actual = None
        for request in case.steps:
            actual = transport.send(request)
        results.append(
            TestResult(
                test_id=case.id,
                passed=actual == case.expected,
                expected=case.expected,
                actual=actual,
                trace_to=list(case.trace_to),
            )
        )
    return results
