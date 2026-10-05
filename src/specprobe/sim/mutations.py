from dataclasses import dataclass
from enum import StrEnum

from ..domain.schema import EcuSpec, Precondition
from .ecu import EcuSimulator


class MutationId(StrEnum):
    WRONG_NRC = "WRONG_NRC"
    MISSING_SESSION_CHECK = "MISSING_SESSION_CHECK"
    MISSING_SECURITY_CHECK_ON_WRITE = "MISSING_SECURITY_CHECK_ON_WRITE"
    DID_LENGTH_OFF_BY_ONE = "DID_LENGTH_OFF_BY_ONE"
    SUBFUNCTION_ACCEPTED_WHEN_UNSUPPORTED = "SUBFUNCTION_ACCEPTED_WHEN_UNSUPPORTED"
    WRONG_NRC_PRIORITY = "WRONG_NRC_PRIORITY"
    SECURITY_NOT_RELOCKED_ON_SESSION_CHANGE = "SECURITY_NOT_RELOCKED_ON_SESSION_CHANGE"
    PRECONDITION_IGNORED = "PRECONDITION_IGNORED"


@dataclass(frozen=True)
class Mutation:
    id: MutationId
    description: str
    field_ids: tuple[str, ...] = ()


MUTATION_DESCRIPTIONS: dict[MutationId, str] = {
    MutationId.WRONG_NRC: "Returns a different negative response code.",
    MutationId.MISSING_SESSION_CHECK: "Skips service, DID, and routine session checks.",
    MutationId.MISSING_SECURITY_CHECK_ON_WRITE: "Allows a secured DID write while locked.",
    MutationId.DID_LENGTH_OFF_BY_ONE: "Accepts one extra DID payload byte.",
    MutationId.SUBFUNCTION_ACCEPTED_WHEN_UNSUPPORTED: "Accepts an unsupported subfunction.",
    MutationId.WRONG_NRC_PRIORITY: (
        "Selects the lowest candidate NRC instead of configured priority."
    ),
    MutationId.SECURITY_NOT_RELOCKED_ON_SESSION_CHANGE: "Retains security after a session switch.",
    MutationId.PRECONDITION_IGNORED: "Skips DID and routine precondition checks.",
}


def mutation_config(mutations: list[Mutation]) -> frozenset[MutationId]:
    return frozenset(item.id for item in mutations)


def mutant_simulator(spec: "EcuSpec", mutations: list[Mutation]) -> "EcuSimulator":
    return MutantEcuSimulator(spec, mutation_config(mutations))


class MutantEcuSimulator(EcuSimulator):
    def __init__(self, spec: EcuSpec, mutations: frozenset[MutationId]) -> None:
        super().__init__(spec)
        self.mutations = mutations

    def _finish(self, sid: int, response: bytes | None) -> bytes | None:
        if (
            MutationId.WRONG_NRC in self.mutations
            and response is not None
            and response[:1] == b"\x7f"
        ):
            nrc = response[2] if response[2] != 0x31 else 0x22
            return response[:2] + bytes((nrc,))
        return response

    def _session_allowed(self, allowed_sessions: list[int]) -> bool:
        return (
            True
            if MutationId.MISSING_SESSION_CHECK in self.mutations
            else super()._session_allowed(allowed_sessions)
        )

    def _unsupported_subfunction_allowed(self) -> bool:
        return MutationId.SUBFUNCTION_ACCEPTED_WHEN_UNSUPPORTED in self.mutations

    def _choose_nrc(self, candidates: list[int]) -> int:
        if MutationId.WRONG_NRC_PRIORITY in self.mutations:
            return min(candidates)
        return super()._choose_nrc(candidates)

    def _security_after_session_change(self) -> int:
        if MutationId.SECURITY_NOT_RELOCKED_ON_SESSION_CHANGE in self.mutations:
            return self.state.security_level
        return 0

    def _write_security_denied(self, required_security: int | None) -> bool:
        return (
            False
            if MutationId.MISSING_SECURITY_CHECK_ON_WRITE in self.mutations
            else super()._write_security_denied(required_security)
        )

    def _allowed_write_lengths(self, length: int) -> set[int]:
        if MutationId.DID_LENGTH_OFF_BY_ONE in self.mutations:
            return {length, length + 1}
        return super()._allowed_write_lengths(length)

    def _preconditions_hold(self, conditions: list[Precondition]) -> bool:
        if MutationId.PRECONDITION_IGNORED in self.mutations:
            return True
        return super()._preconditions_hold(conditions)

    def _unsupported_control(self, control: int, supported: list[int]) -> int | None:
        if (
            control not in supported
            and MutationId.SUBFUNCTION_ACCEPTED_WHEN_UNSUPPORTED in self.mutations
        ):
            return supported[0] if supported else control
        return super()._unsupported_control(control, supported)
