"""Bounded UDS exchanges over an explicitly configured, message-level adapter.

No CAN interface is opened by this module. Hardware adapters must implement the
interface and require an approval reference supplied by the caller.
"""

import math
from dataclasses import dataclass
from typing import Protocol

from ..domain.schema import Timing


@dataclass(frozen=True)
class Frame:
    payload: bytes
    elapsed_ms: float


class MessageAdapter(Protocol):
    is_hardware: bool

    def transmit(self, request: bytes) -> None: ...
    def receive(self, timeout_ms: float) -> Frame | None: ...
    def set_environment(self, environment: dict[str, object]) -> None: ...


class ControlledTransport:
    def __init__(
        self,
        adapter: MessageAdapter,
        timing: Timing,
        *,
        hardware_enabled: bool = False,
        approval_reference: str = "",
        max_pending: int = 10,
    ) -> None:
        if adapter.is_hardware and (not hardware_enabled or not approval_reference.strip()):
            raise PermissionError(
                "Hardware execution requires explicit enablement and approval reference"
            )
        if max_pending < 1:
            raise ValueError("max_pending must be positive")
        self.adapter = adapter
        self.timing = timing
        self.approval_reference = approval_reference
        self.max_pending = max_pending
        self.history: list[Frame] = []

    def set_environment(self, environment: dict[str, object]) -> None:
        self.adapter.set_environment(environment)

    def send(self, request: bytes) -> bytes | None:
        if not request:
            raise ValueError("Empty diagnostic request")
        self.history = []
        self.adapter.transmit(request)
        timeout = float(self.timing.p2_ms)
        pending = 0
        while True:
            frame = self.adapter.receive(timeout)
            if frame is None:
                if pending:
                    raise TimeoutError("P2-star expired after response pending")
                return None
            if (
                not math.isfinite(frame.elapsed_ms)
                or frame.elapsed_ms < 0
                or frame.elapsed_ms > timeout
            ):
                raise TimeoutError("P2/P2-star response deadline exceeded")
            self.history.append(frame)
            response = frame.payload
            if not response or (
                response[0] == 0x7F and (len(response) != 3 or response[1] != request[0])
            ):
                raise ConnectionError("Malformed or unrelated negative response")
            if response[0] == 0x7F and response[2] == 0x78:
                pending += 1
                if pending > self.max_pending:
                    raise TimeoutError("Response-pending limit exceeded")
                timeout = float(self.timing.p2_star_ms)
                continue
            if response[0] != 0x7F and response[0] != (request[0] + 0x40) & 0xFF:
                raise ConnectionError("Response service identifier does not match request")
            if response[0] != 0x7F:
                lengths = {0x10: 2, 0x11: 2, 0x22: 3, 0x27: 2, 0x2E: 3, 0x31: 4, 0x3E: 2}
                if len(response) < lengths.get(request[0], 1):
                    raise ConnectionError("Truncated positive response")
                echo_lengths = {0x10: 1, 0x11: 1, 0x27: 1, 0x3E: 1, 0x22: 2, 0x2E: 2, 0x31: 3}
                echo = echo_lengths.get(request[0], 0)
                wanted = bytearray(request[1 : 1 + echo])
                if wanted and request[0] in {0x10, 0x11, 0x27, 0x3E, 0x31}:
                    wanted[0] &= 0x7F
                if response[1 : 1 + echo] != wanted:
                    raise ConnectionError("Positive response echo does not match request")
            return response


class SessionClock:
    """Virtual S3 model for simulator validation, never a wall-clock ECU claim."""

    def __init__(self, s3_ms: int) -> None:
        if s3_ms <= 0:
            raise ValueError("S3 must be positive")
        self.s3_ms = s3_ms
        self.session = 1
        self.idle_ms = 0.0

    def request(self, session: int | None = None) -> None:
        self.idle_ms = 0
        if session is not None:
            self.session = session

    def advance(self, elapsed_ms: float) -> bool:
        if elapsed_ms < 0:
            raise ValueError("Time cannot move backwards")
        self.idle_ms += elapsed_ms
        expired = self.idle_ms >= self.s3_ms
        if expired:
            self.session = 1
        return expired
