from dataclasses import dataclass

from specprobe.demo import build_spec
from specprobe.rules.oracle import State, step
from specprobe.sim.ecu import EcuSimulator


@dataclass(frozen=True)
class GoldenVector:
    name: str
    setup: tuple[bytes, ...]
    request: bytes
    expected: bytes | None
    environment: dict[str, object]
    reason: str


# These bytes are hand-written protocol expectations; neither implementation generated them.
VECTORS = (
    GoldenVector(
        "session-positive", (), b"\x10\x03", b"\x50\x03", {}, "extended session is accepted"
    ),
    GoldenVector(
        "session-invalid", (), b"\x10\xff", b"\x7f\x10\x31", {}, "unknown session is out of range"
    ),
    GoldenVector(
        "reset-positive", (), b"\x11\x01", b"\x51\x01", {}, "hard reset subfunction is supported"
    ),
    GoldenVector(
        "reset-subfunction",
        (),
        b"\x11\x02",
        b"\x7f\x11\x12",
        {},
        "reset subfunction is unsupported",
    ),
    GoldenVector(
        "reset-length", (), b"\x11", b"\x7f\x11\x13", {}, "reset requires a subfunction byte"
    ),
    GoldenVector(
        "seed-positive", (), b"\x27\x01", b"\x67\x01\xa5\x01", {}, "level one seed is issued"
    ),
    GoldenVector(
        "key-sequence",
        (),
        b"\x27\x02\xff\x5b",
        b"\x7f\x27\x24",
        {},
        "key without a seed is a sequence error",
    ),
    GoldenVector(
        "read-positive",
        (b"\x10\x03", b"\x27\x01", b"\x27\x02\xff\x5b"),
        b"\x22\x10\x00",
        b"\x62\x10\x00\x00\x00\x00\x00",
        {},
        "secured DID returns its fixed four-byte value",
    ),
    GoldenVector(
        "read-length",
        (),
        b"\x22\x10",
        b"\x7f\x22\x13",
        {},
        "read DID requires two identifier bytes",
    ),
    GoldenVector(
        "read-range", (), b"\x22\xff\xff", b"\x7f\x22\x31", {}, "unknown DID is out of range"
    ),
    GoldenVector(
        "read-security",
        (),
        b"\x22\x10\x00",
        b"\x7f\x22\x33",
        {},
        "secured read is denied while locked",
    ),
    GoldenVector(
        "write-positive",
        (b"\x10\x03", b"\x27\x01", b"\x27\x02\xff\x5b"),
        b"\x2e\x10\x00\x00\x00\x00\x00",
        b"\x6e\x10\x00",
        {"signal_0": True},
        "secured write accepts the exact payload length",
    ),
    GoldenVector(
        "write-security",
        (b"\x10\x03",),
        b"\x2e\x10\x00\x00\x00\x00\x00",
        b"\x7f\x2e\x33",
        {"signal_0": True},
        "write security is checked before payload mutation",
    ),
    GoldenVector(
        "write-length",
        (b"\x10\x03", b"\x27\x01", b"\x27\x02\xff\x5b"),
        b"\x2e\x10\x00\x00\x00",
        b"\x7f\x2e\x13",
        {"signal_0": True},
        "write rejects a short payload",
    ),
    GoldenVector(
        "write-condition",
        (b"\x10\x03", b"\x27\x01", b"\x27\x02\xff\x5b"),
        b"\x2e\x10\x00\x00\x00\x00\x00",
        b"\x7f\x2e\x22",
        {"signal_0": False},
        "write requires the structured signal precondition",
    ),
    GoldenVector(
        "routine-positive",
        (b"\x10\x03", b"\x27\x01", b"\x27\x02\xff\x5b"),
        b"\x31\x01\x20\x00\x00",
        b"\x71\x01\x20\x00",
        {},
        "routine start accepts its one-byte parameter",
    ),
    GoldenVector(
        "routine-range",
        (),
        b"\x31\x01\xff\xff",
        b"\x7f\x31\x7f",
        {},
        "unknown routine is out of range after service gates",
    ),
    GoldenVector(
        "routine-control",
        (b"\x10\x03", b"\x27\x01", b"\x27\x02\xff\x5b"),
        b"\x31\x7f\x20\x00",
        b"\x7f\x31\x12",
        {},
        "unsupported control type is rejected",
    ),
    GoldenVector(
        "routine-length",
        (b"\x10\x03", b"\x27\x01", b"\x27\x02\xff\x5b"),
        b"\x31\x01\x20\x00",
        b"\x7f\x31\x13",
        {},
        "routine start requires one parameter byte",
    ),
    GoldenVector(
        "tester-positive",
        (),
        b"\x3e\x00",
        b"\x7e\x00",
        {},
        "tester present returns its positive response",
    ),
    GoldenVector(
        "tester-suppressed",
        (),
        b"\x3e\x80",
        None,
        {},
        "suppress-positive-response requests no response",
    ),
    GoldenVector(
        "tester-subfunction",
        (),
        b"\x3e\x01",
        b"\x7f\x3e\x12",
        {},
        "tester present only supports zero subfunction",
    ),
    GoldenVector(
        "tester-length",
        (),
        b"\x3e\x00\x00",
        b"\x7f\x3e\x13",
        {},
        "tester present has at most one subfunction byte",
    ),
    GoldenVector(
        "unknown-sid",
        (),
        b"\x99",
        b"\x7f\x99\x11",
        {},
        "unknown service uses NRC service-not-supported",
    ),
)


def test_golden_vectors_match_both_implementations() -> None:
    spec = build_spec()
    for vector in VECTORS:
        state = State(session=1)
        simulator = EcuSimulator(spec)
        simulator.set_environment(vector.environment)
        for setup_request in vector.setup:
            _, state = step(spec, state, vector.environment, setup_request)
            simulator.send(setup_request)
        oracle_response, _ = step(spec, state, vector.environment, vector.request)
        assert oracle_response.bytes == vector.expected, vector.name
        assert simulator.send(vector.request) == vector.expected, vector.name


def test_golden_vectors_decode_with_udsoncan() -> None:
    from udsoncan import Request

    for vector in VECTORS:
        if vector.request[0] == 0x99:
            continue
        request = Request.from_payload(vector.request)
        assert request.service.request_id() == vector.request[0], vector.name
        if len(vector.request) > 1 and vector.request[0] in {0x10, 0x11, 0x27, 0x31, 0x3E}:
            assert request.subfunction == vector.request[1] & 0x7F, vector.name
