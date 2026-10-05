import argparse
from collections.abc import Sequence
from time import perf_counter

from specprobe.demo import build_spec
from specprobe.domain.schema import EcuSpec
from specprobe.domain.testcase import TestCase
from specprobe.gen.generator import generate_suite
from specprobe.sim.auto_mutants import (
    classify_survivors,
    run_auto_mutants,
)
from tests.baseline_suite import build_baseline_suite


def validate_suite(spec: EcuSpec, suite: Sequence[TestCase]) -> None:
    from specprobe.runner.executor import run_suite
    from specprobe.sim.ecu import EcuSimulator

    failures = [
        result.test_id
        for result in run_suite(list(suite), EcuSimulator(spec))
        if not result.passed
    ]
    if failures:
        raise ValueError(f"suite failed on clean simulator: {failures}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--author-time-minutes", type=float, default=None)
    args = parser.parse_args()
    spec = build_spec()
    started = perf_counter()
    generated = generate_suite(spec)
    generation_time = perf_counter() - started
    rows: list[tuple[str, int, int, int, int, int, int, int, float, float]] = []
    for name, suite in (("baseline", build_baseline_suite()), ("generated", generated)):
        validate_suite(spec, suite)
        auto = run_auto_mutants(spec, suite)
        compilable = [item for item in auto if item.compilable]
        survivors = [item for item in compilable if not item.killed_by and not item.crashed_by]
        reasons = classify_survivors(spec, survivors)
        equivalent = sum(
            reasons.get(item.mutation_id) == "equivalent-mutant candidate" for item in survivors
        )
        genuine = len(survivors) - equivalent
        killed = sum(bool(item.killed_by) for item in compilable)
        crashes = sum(bool(item.crashed_by) for item in compilable)
        raw_score = killed / len(compilable) if compilable else 0.0
        adjusted_denominator = len(compilable) - equivalent
        adjusted_score = killed / adjusted_denominator if adjusted_denominator else 1.0
        print(
            f"{name} mechanical mutants: total={len(auto)}, compilable={len(compilable)}, "
            f"output mismatch={killed}, crash={crashes}, survived={len(survivors)}, "
            f"equivalent={equivalent}, genuine gap={genuine}, "
            f"raw score={raw_score:.1%}, adjusted score={adjusted_score:.1%}"
        )
        for item in survivors:
            if reasons[item.mutation_id].startswith("genuine gap"):
                print(
                    f"genuine-gap survivor {item.mutation_id}: operator={item.operator}, "
                    f"line={item.source_line}, diff={item.original_code} -> {item.mutated_code}"
                )
        rows.append(
            (
                name,
                len(suite),
                len(auto),
                len(compilable),
                killed,
                crashes,
                len(survivors),
                equivalent,
                raw_score,
                adjusted_score,
            )
        )
    print(
        "suite | size | total mutants | compilable | output mismatch | crash | survived | "
        "equivalent | genuine gap | raw score | adjusted score"
    )
    for (
        name,
        size,
        total,
        compilable_count,
        killed,
        crashes,
        survived,
        equivalent,
        raw_score,
        adjusted_score,
    ) in rows:
        print(
            f"{name} | {size} | {total} | {compilable_count} | {killed} | {crashes} | "
            f"{survived} | {equivalent} | {survived - equivalent} | {raw_score:.1%} | "
            f"{adjusted_score:.1%}"
        )
    print(f"generated wall-clock time: {generation_time:.6f}s")
    author_time = (
        f"{args.author_time_minutes:.1f} minutes"
        if args.author_time_minutes is not None
        else "not provided"
    )
    print(f"baseline author time: {author_time}")


if __name__ == "__main__":
    main()
