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


class Mutation:
    def __init__(self, mutation_id: MutationId, description: str, field_ids: list[str] | None = None) -> None:
        self.id = mutation_id
        self.description = description
        self.field_ids = field_ids or []


def apply_mutations(ecu: object, mutations: list[Mutation]) -> None:
    setattr(ecu, "mutations", {mutation.id for mutation in mutations})
