from typing import Protocol


class Transport(Protocol):
    def send(self, request: bytes) -> bytes | None: ...

    def set_environment(self, environment: dict[str, object]) -> None: ...


class InMemoryTransport:
    def __init__(self, ecu: Transport) -> None:
        self.ecu = ecu

    def send(self, request: bytes) -> bytes | None:
        return self.ecu.send(request)

    def set_environment(self, environment: dict[str, object]) -> None:
        self.ecu.set_environment(environment)
