import pytest
from udsoncan import Response
from udsoncan.services import (
    ECUReset,
    RoutineControl,
    SecurityAccess,
    TesterPresent,
    WriteDataByIdentifier,
)

from tests.golden_vectors import VECTORS


@pytest.mark.parametrize(
    "vector",
    [
        v
        for v in VECTORS
        if v.expected and v.expected[0] != 0x7F and v.request[0] in {0x11, 0x27, 0x31, 0x2E, 0x3E}
    ],
    ids=lambda v: v.name,
)
def test_positive_outcomes_decode_independently(vector):
    response = Response.from_payload(vector.expected)
    interpreters = {
        0x11: ECUReset,
        0x27: SecurityAccess,
        0x31: RoutineControl,
        0x2E: WriteDataByIdentifier,
        0x3E: TesterPresent,
    }
    service = interpreters[vector.request[0]]
    decoded = (
        service.interpret_response(response, mode=SecurityAccess.Mode.RequestSeed)
        if service is SecurityAccess
        else service.interpret_response(response)
    )
    assert decoded.valid and decoded.positive
    data = decoded.service_data
    if service is ECUReset:
        assert data.reset_type_echo == vector.request[1]
    elif service is SecurityAccess:
        assert data.security_level_echo == vector.request[1] and data.seed == vector.expected[2:]
    elif service is RoutineControl:
        assert data.routine_id_echo == int.from_bytes(vector.request[2:4], "big")
    elif service is WriteDataByIdentifier:
        assert data.did_echo == int.from_bytes(vector.request[1:3], "big")
    elif service is TesterPresent:
        assert data.subfunction_echo == 0
