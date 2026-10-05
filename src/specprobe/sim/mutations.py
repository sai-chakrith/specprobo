from dataclasses import dataclass
from enum import StrEnum


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
