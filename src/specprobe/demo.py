from pathlib import Path

from .data_loader import load_spec
from .domain.schema import EcuSpec
from .domain.testcase import TestCase
from .gen.generator import generate_suite
from .runner.executor import run_suite
from .runner.report import MutationResult, Report
from .sim.auto_mutants import auto_mutation_score, classify_survivors, run_auto_mutants
from .sim.ecu import EcuSimulator
from .sim.mutations import MUTATION_DESCRIPTIONS, Mutation, MutationId, mutant_simulator


def build_spec() -> EcuSpec:
    path = Path(__file__).parents[2] / "data" / "synthetic" / "ground_truth" / "oem_a.json"
    return load_spec(path)


def run_mutations(spec: EcuSpec, suite: list[TestCase]) -> Report:
    baseline_results = run_suite(suite, EcuSimulator(spec))
    mutation_results: list[MutationResult] = []
    for mutation_id in MutationId:
        mutant = mutant_simulator(
            spec, [Mutation(mutation_id, MUTATION_DESCRIPTIONS[mutation_id])]
        )
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
    generated = generate_suite(spec)
    _print_comparison(spec, generated)


def _print_comparison(spec: EcuSpec, generated: list[TestCase]) -> None:
    from tests.baseline_suite import build_baseline_suite

    rows: list[tuple[str, int, float, float, str]] = []
    for name, suite in (("baseline", build_baseline_suite()), ("generated", generated)):
        named = run_mutations(spec, suite)
        auto = run_auto_mutants(spec, suite)
        survivor_ids = [item.mutation_id for item in auto if not item.killed_by]
        classifications = classify_survivors(spec, [item for item in auto if not item.killed_by])
        survivor_text = (
            ", ".join(f"{item} ({classifications[item]})" for item in survivor_ids) or "none"
        )
        rows.append(
            (name, len(suite), named.mutation_score, auto_mutation_score(spec, auto), survivor_text)
        )
    print("suite | size | named-mutant score | auto-mutant score | survivors")
    for name, size, named_score, auto_score, survivor_summary in rows:
        print(f"{name} | {size} | {named_score:.1%} | {auto_score:.1%} | {survivor_summary}")


if __name__ == "__main__":
    main()
