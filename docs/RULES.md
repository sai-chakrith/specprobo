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
| Structured write/routine precondition is false | `0x22` | `preconditions` |
| Structured read precondition is false | `0x22` | `read_preconditions` |
| Session switch target is not specified | `0x31` | `Session.id` |
| Routine control type is unsupported | `0x12` | `Routine.control_types` |
| Tester-present suppress-positive-response bit is set | No response | `Service.suppress_positive_response_supported` |

For competing service-gate failures, the first matching NRC in `EcuSpec.nrc_priority` wins. DID/routine handlers also have modeled staged checks; this is not proof of every OEM NRC precedence rule. A complete explicit ordering for supported model errors is required; generation does not silently fill missing priorities from `rules/priority.py`.

Model conventions: security level zero is locked; service subfunction gate values remove the suppress-positive-response bit; typed missing/mismatched precondition signals evaluate false. Empty DID read/write session permissions disable that direction; a DID with neither direction declared blocks generation. Empty service session gates remain an unrestricted-service model convention that requires reviewer acceptance. These modeled rules need independent ECU validation.
