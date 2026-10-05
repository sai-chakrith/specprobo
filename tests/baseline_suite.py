from specprobe.demo import build_spec
from specprobe.domain.testcase import TestCase, TraceRef
from specprobe.rules.oracle import State, step

_UNLOCKED_EXTENDED = (b"\x10\x03", b"\x27\x01", b"\x27\x02\xff\x5b")


def _case(
    name: str, setup: tuple[bytes, ...], request: bytes, environment: dict[str, object]
) -> TestCase:
    spec = build_spec()
    state = State(session=1)
    for message in setup:
        _, state = step(spec, state, environment, message)
    expected, _ = step(spec, state, environment, request)
    return TestCase(
        id=name,
        trace_to=[TraceRef(field_id="synthetic.baseline", page=1)],
        preconditions={},
        setup_steps=list(setup),
        steps=[request],
        environment=environment,
        expected=expected.bytes,
        tags=["baseline", name],
    )


def build_baseline_suite() -> list[TestCase]:
    cases: list[TestCase] = []
    for index in range(10):
        did = 0x1000 + index
        cases.append(
            _case(
                f"baseline-read-{index}",
                _UNLOCKED_EXTENDED,
                bytes((0x22, did >> 8, did & 0xFF)),
                {},
            )
        )
    for index in range(10):
        did = 0x1000 + index
        cases.append(
            _case(
                f"baseline-write-{index}",
                _UNLOCKED_EXTENDED,
                bytes((0x2E, did >> 8, did & 0xFF, 0, 0, 0, 0)),
                {f"signal_{index}": True},
            )
        )
    cases.extend(
        [
            _case("baseline-unknown-did", (), b"\x22\xff\xff", {}),
            _case("baseline-read-short", (), b"\x22\x10", {}),
            _case(
                "baseline-write-short", _UNLOCKED_EXTENDED, b"\x2e\x10\x00\x00", {"signal_0": True}
            ),
            _case(
                "baseline-write-locked",
                (b"\x10\x03",),
                b"\x2e\x10\x00\x00\x00\x00\x00",
                {"signal_0": True},
            ),
            _case(
                "baseline-write-condition",
                _UNLOCKED_EXTENDED,
                b"\x2e\x10\x00\x00\x00\x00\x00",
                {"signal_0": False},
            ),
            _case("baseline-seed", (), b"\x27\x01", {}),
            _case("baseline-key-sequence", (), b"\x27\x02\xff\x5b", {}),
            _case("baseline-key-invalid", (b"\x27\x01",), b"\x27\x02\x00\x00", {}),
            _case("baseline-routine", _UNLOCKED_EXTENDED, b"\x31\x01\x20\x00\x00", {}),
            _case("baseline-routine-control", _UNLOCKED_EXTENDED, b"\x31\x7f\x20\x00", {}),
            _case("baseline-routine-length", _UNLOCKED_EXTENDED, b"\x31\x01\x20\x00", {}),
            _case("baseline-tester", (), b"\x3e\x00", {}),
            _case("baseline-tester-spr", (), b"\x3e\x80", {}),
            _case("baseline-tester-invalid", (), b"\x3e\x01", {}),
            _case("baseline-session-invalid", (), b"\x10\xff", {}),
            _case("baseline-reset", (), b"\x11\x01", {}),
            _case("baseline-reset-invalid", (), b"\x11\x02", {}),
            _case("baseline-unknown-service", (), b"\x99", {}),
        ]
    )
    return cases
