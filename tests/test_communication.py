import pytest

from specprobe.domain.schema import Timing
from specprobe.runner.executor import response_matches
from specprobe.sim.controlled import ControlledTransport, Frame, SessionClock


class Adapter:
    is_hardware = False

    def __init__(self, frames):
        self.frames = iter(frames)
        self.timeouts = []

    def transmit(self, request):
        pass

    def receive(self, timeout_ms):
        self.timeouts.append(timeout_ms)
        return next(self.frames)

    def set_environment(self, environment):
        pass


TIMING = Timing(p2_ms=50, p2_star_ms=500, s3_ms=1000)


def test_pending_uses_p2star_then_validates_final_response():
    adapter = Adapter([Frame(b"\x7f\x22\x78", 40), Frame(b"\x62\xf1\x90\x01", 300)])
    transport = ControlledTransport(adapter, TIMING)
    assert transport.send(b"\x22\xf1\x90") == b"\x62\xf1\x90\x01"
    assert adapter.timeouts == [50, 500]


@pytest.mark.parametrize(
    "frames,error",
    [
        ([Frame(b"\x62", 51)], TimeoutError),
        ([Frame(b"\x7f\x22\x78", 20), None], TimeoutError),
        ([Frame(b"\x7f\x10\x31", 10)], ConnectionError),
        ([Frame(b"\x7f", 10)], ConnectionError),
        ([Frame(b"", 10)], ConnectionError),
        ([Frame(b"\x50\x01", 10)], ConnectionError),
    ],
)
def test_timing_and_framing_failures(frames, error):
    with pytest.raises(error):
        ControlledTransport(Adapter(frames), TIMING).send(b"\x22\xf1\x90")


def test_hardware_requires_both_explicit_configuration_and_approval():
    adapter = Adapter([])
    adapter.is_hardware = True
    with pytest.raises(PermissionError):
        ControlledTransport(adapter, TIMING)
    with pytest.raises(PermissionError):
        ControlledTransport(adapter, TIMING, hardware_enabled=True)
    ControlledTransport(
        adapter, TIMING, hardware_enabled=True, approval_reference="BENCH-REVIEW-01"
    )


def test_s3_expiry_and_tester_activity_reset():
    clock = SessionClock(1000)
    clock.request(3)
    assert not clock.advance(999)
    clock.request()
    assert not clock.advance(999)
    assert clock.advance(1)
    assert clock.session == 1


def test_response_mask_does_not_hide_length_mismatch():
    assert response_matches(b"\x62\x01", b"\x62\x07", b"\xff\x00")
    assert not response_matches(b"\x62\x01", b"\x62", b"\xff\x00")
