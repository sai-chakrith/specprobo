from ..domain.schema import Service
from .uds_constants import NRC_INCORRECT_LENGTH, NRC_SUBFUNCTION_NOT_SUPPORTED


def validate_request(service: Service, request: bytes) -> set[int]:
    candidates: set[int] = set()
    if not request:
        candidates.add(NRC_INCORRECT_LENGTH)
        return candidates
    if service.subfunctions:
        subfunction = request[1] & 0x7F if len(request) > 1 else None
        if subfunction not in {item.value for item in service.subfunctions}:
            candidates.add(NRC_SUBFUNCTION_NOT_SUPPORTED)
    return candidates
