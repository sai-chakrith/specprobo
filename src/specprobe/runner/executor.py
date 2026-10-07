from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..domain.testcase import TestCase
from ..sim.transport import Transport


class StepResult(BaseModel):
    model_config = ConfigDict(ser_json_bytes="hex")
    phase: str
    index: int
    request: bytes
    expected: bytes | None
    actual: bytes | None
    passed: bool


class TestResult(BaseModel):
    model_config = ConfigDict(ser_json_bytes="hex")
    test_id: str
    passed: bool
    expected: bytes | None
    actual: bytes | None
    trace_to: list[object]
    failure_kind: (
        Literal[
            "setup_failure", "communication_failure", "response_mismatch", "configuration_failure"
        ]
        | None
    ) = None
    detail: str = ""
    checks: list[StepResult] = Field(default_factory=list)


def response_matches(
    expected: bytes | None, actual: bytes | None, mask: bytes | None = None
) -> bool:
    if expected is None or actual is None:
        return expected is actual
    if len(actual) != len(expected):
        return False
    if mask is None:
        return actual == expected
    if len(mask) != len(expected):
        raise ValueError("Response mask length does not match expected response")
    return all((a & m) == (b & m) for a, b, m in zip(expected, actual, mask, strict=True))


def run_suite(cases: list[TestCase], transport: Transport) -> list[TestResult]:
    results = []
    for case in cases:
        result = TestResult(
            test_id=case.id,
            passed=True,
            expected=case.expected,
            actual=None,
            trace_to=list(case.trace_to),
        )
        try:
            if not case.steps:
                raise ValueError("Case has no diagnostic steps")
            if len(case.setup_expected) != len(case.setup_steps):
                raise ValueError("Every setup request requires an explicit expected response")
            if any(value is None or not value or value[0] == 0x7F for value in case.setup_expected):
                raise ValueError("Setup expectations must establish state with positive responses")
            if (len(case.steps) > 1 or case.step_expected) and len(case.step_expected) != len(
                case.steps
            ):
                raise ValueError("Every intermediate step requires an explicit expected response")
            if case.step_expected and case.step_expected[-1] != case.expected:
                raise ValueError("Final response expectation conflicts with step expectations")
            if case.response_mask is not None and (
                case.expected is None or len(case.response_mask) != len(case.expected)
            ):
                raise ValueError("Response mask length does not match expected response")
            reset = getattr(transport, "reset_case", None)
            if reset is not None:
                reset()
            transport.set_environment(case.environment)
            for phase, requests, expectations in [
                ("setup", case.setup_steps, case.setup_expected),
                ("step", case.steps, case.step_expected),
            ]:
                if phase == "step" and case.idle_before_ms:
                    advance = getattr(transport, "advance_time", None)
                    if advance is None:
                        raise ValueError("Transport does not support a controlled idle interval")
                    advance(case.idle_before_ms)
                    observed = getattr(transport, "observed_session", None)
                    wanted = case.preconditions.get("expected_session_after_idle")
                    if wanted is not None:
                        if observed is None:
                            raise ValueError("S3 case requires a validated session observer")
                        if observed() != wanted:
                            result.passed = False
                            result.failure_kind = "response_mismatch"
                            result.detail = "Session state differs at S3 boundary"
                            break
                if expectations and len(expectations) != len(requests):
                    raise ValueError(f"{phase} expectation count differs from request count")
                for index, request in enumerate(requests):
                    expected = (
                        expectations[index]
                        if expectations
                        else (
                            case.expected
                            if phase == "step" and index == len(requests) - 1
                            else None
                        )
                    )
                    actual = transport.send(request)
                    result.actual = actual
                    mask = (
                        case.response_mask
                        if phase == "step" and index == len(requests) - 1
                        else None
                    )
                    passed = response_matches(expected, actual, mask)
                    result.checks.append(
                        StepResult(
                            phase=phase,
                            index=index,
                            request=request,
                            expected=expected,
                            actual=actual,
                            passed=passed,
                        )
                    )
                    if not passed:
                        result.passed = False
                        result.failure_kind = (
                            "communication_failure"
                            if actual is None and expected is not None
                            else ("setup_failure" if phase == "setup" else "response_mismatch")
                        )
                        result.detail = f"{phase} response failed at index {index}"
                        break
                if not result.passed:
                    break
        except (OSError, TimeoutError, ConnectionError) as error:
            result.passed = False
            result.failure_kind = "communication_failure"
            result.detail = str(error)
        except ValueError as error:
            result.passed = False
            result.failure_kind = "configuration_failure"
            result.detail = str(error)
        results.append(result)
    return results
