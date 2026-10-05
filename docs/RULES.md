# Deterministic Rules

The oracle is the only source of expected responses. The simulator reproduces these rules independently for differential testing.

| Condition | NRC | Spec field consulted |
| --- | --- | --- |
| Unknown service identifier | `0x11` | No service match |
| Known service is not allowed in the active session | `0x7F` | `Service.allowed_sessions` |
| Unsupported service subfunction | `0x12` | `Service.subfunctions` |
| Subfunction is not allowed in the active session | `0x7E` | `Subfunction.allowed_sessions` |
| Request length is invalid | `0x13` | Service/DID/routine length rules |
| DID or routine identifier is unknown | `0x31` | `DataIdentifier.did` / `Routine.rid` |
| DID or routine security level is not unlocked | `0x33` | `read_security`, `write_security`, `Routine.security` |
| Security key was sent before a seed or for the wrong level | `0x24` | Security state |
| Security key does not match the deterministic key function | `0x35` | Security state and key exchange |
| Structured precondition is false | `0x22` | `preconditions` |
| Session switch target is not specified | `0x31` | `Session.id` |
| Routine control type is unsupported | `0x12` | `Routine.control_types` |
| Tester-present suppress-positive-response bit is set | No response | `Service.suppress_positive_response_supported` |

When several rules apply, the first matching NRC in `EcuSpec.nrc_priority` wins. The default is data in `rules/priority.py`; OEM specs may replace it.

Conservative choices for this pass: security level zero is locked, service subfunction values are compared after removing only the suppress-positive-response bit, and a missing numeric precondition signal evaluates false.
