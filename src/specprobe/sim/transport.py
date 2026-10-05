from typing import Protocol


class Transport(Protocol):
    def send(self, request: bytes) -> bytes | None: ...


class InMemoryTransport:
    def __init__(self, ecu: object) -> None:
        self.ecu = ecu

    def send(self, request: bytes) -> bytes | None:
        return self.ecu.handle(request)  # type: ignore[attr-defined]
