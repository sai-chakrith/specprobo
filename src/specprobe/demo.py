from specprobe.domain.schema import (
    DataIdentifier,
    EcuSpec,
    Precondition,
    Routine,
    SecurityLevel,
    Service,
    Session,
    Subfunction,
    Timing,
)
from specprobe.domain.testcase import TestCase
from specprobe.gen.generator import generate_suite
from specprobe.runner.executor import run_suite
from specprobe.runner.report import MutationResult, Report
from specprobe.sim.ecu import EcuSimulator
from specprobe.sim.mutations import MUTATION_DESCRIPTIONS, Mutation, MutationId


def build_spec() -> EcuSpec:
    conditions = [
        Precondition(
            kind="signal",
            signal=f"signal_{index}",
            op="==",
            value=True,
            source_text="synthetic condition",
        )
        for index in range(6)
    ]
    dids = [
        DataIdentifier(
            did=0x1000 + index,
            name=f"DID-{index}",
            length_bytes=4,
            encoding="bytes",
            read_sessions=[1, 3],
            write_sessions=[3],
            read_security=1,
            write_security=1,
            preconditions=[conditions[index % 6]],
        )
        for index in range(10)
    ]
    routines = [
        Routine(
            rid=0x2000 + index,
            name=f"Routine-{index}",
            control_types=[1, 2, 3],
            sessions=[3],
            security=1,
            parameter_lengths={1: 1, 2: 0, 3: 2},
            preconditions=[conditions[index + 3]],
        )
        for index in range(3)
    ]
    return EcuSpec(
        ecu_name="SYNTH-RICH-ECU",
        oem="OEM-A",
        version="1",
        sessions=[Session(id=1, name="default"), Session(id=3, name="extended")],
        security_levels=[
            SecurityLevel(level=0, name="locked"),
            SecurityLevel(level=1, name="level1"),
        ],
        services=[
            Service(sid=0x10, name="SessionControl"),
            Service(sid=0x11, name="Reset", subfunctions=[Subfunction(value=1, name="hard")]),
            Service(sid=0x22, name="ReadDataByIdentifier"),
            Service(sid=0x27, name="SecurityAccess"),
            Service(sid=0x2E, name="WriteDataByIdentifier"),
            Service(
                sid=0x31, name="RoutineControl", allowed_sessions=[3], required_security_level=1
            ),
            Service(sid=0x3E, name="TesterPresent", suppress_positive_response_supported=True),
        ],
        dids=dids,
        routines=routines,
        timing=Timing(p2_ms=50, p2_star_ms=5000, s3_ms=5000),
        nrc_priority=[0x13, 0x12, 0x11, 0x7F, 0x7E, 0x33, 0x35, 0x24, 0x31, 0x22],
    )


def run_mutations(spec: EcuSpec, suite: list[TestCase]) -> Report:
    baseline_results = run_suite(suite, EcuSimulator(spec))
    mutation_results: list[MutationResult] = []
    for mutation_id in MutationId:
        mutant = EcuSimulator(spec, [Mutation(mutation_id, MUTATION_DESCRIPTIONS[mutation_id])])
        results = run_suite(suite, mutant)
        mutation_results.append(
            MutationResult(
                mutation_id.value,
                MUTATION_DESCRIPTIONS[mutation_id],
                [],
                [result.test_id for result in results if not result.passed],
            )
        )
    return Report(baseline_results, mutation_results)


def main() -> None:
    spec = build_spec()
    suite = generate_suite(spec)
    report = run_mutations(spec, suite)
    print(f"clean: {sum(result.passed for result in report.results)}/{len(report.results)} passed")
    print(f"mutation score: {report.mutation_score:.1%}")
    print(
        "undetected: "
        + ", ".join(item.mutation_id for item in report.mutation_results if not item.killed_by)
        or "undetected: none"
    )


if __name__ == "__main__":
    main()
