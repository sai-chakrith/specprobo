DEFAULT_NRC_PRIORITY = [0x13, 0x12, 0x7F, 0x7E, 0x33, 0x31, 0x22]


def choose_nrc(candidates: set[int], priority: list[int]) -> int | None:
    return next((nrc for nrc in priority if nrc in candidates), None)
