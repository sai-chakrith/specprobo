import argparse
from time import perf_counter

from specprobe.demo import build_spec, run_mutations
from specprobe.gen.generator import generate_suite
from specprobe.sim.auto_mutants import (
    add_general_survivor_rules,
    auto_mutation_score,
    classify_survivors,
    run_auto_mutants,
)
from tests.baseline_suite import build_baseline_suite


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--author-time-minutes", type=float, default=None)
    args = parser.parse_args()
    spec = build_spec()
    started = perf_counter()
    generated = generate_suite(spec)
    generation_time = perf_counter() - started
    rows: list[tuple[str, int, float, float, str]] = []
    for name, suite in (("baseline", build_baseline_suite()), ("generated", generated)):
        named = run_mutations(spec, suite)
        auto = run_auto_mutants(spec, suite)
        compilable = [item for item in auto if item.compilable]
        survivors = [item for item in compilable if not item.killed_by]
        reasons = classify_survivors(spec, survivors)
        if name == "generated":
            rules = add_general_survivor_rules(spec, suite, survivors)
            if rules:
                print(f"{name} general survivor rules added: {', '.join(rules)}")
                auto = run_auto_mutants(spec, suite)
                compilable = [item for item in auto if item.compilable]
                survivors = [item for item in compilable if not item.killed_by]
                reasons = classify_survivors(spec, survivors)
        survivor_text = ", ".join(
            f"{item.mutation_id} ({reasons[item.mutation_id]})" for item in survivors
        ) or "none"
        print(
            f"{name} mechanical mutants: total={len(auto)}, "
            f"killed={len(compilable) - len(survivors)}, "
            f"survived={len(survivors)}, uncompilable={len(auto) - len(compilable)}"
        )
        for item in survivors:
            print(
                f"survivor {item.mutation_id}: operator={item.operator}, line={item.source_line}, "
                f"diff={item.original_code} -> {item.mutated_code}, "
                f"classification={item.classification}"
            )
        rows.append(
            (name, len(suite), named.mutation_score, auto_mutation_score(spec, auto), survivor_text)
        )
    print("suite | size | named-mutant score | mechanical-mutant score | survivors")
    for name, size, named_score, auto_score, survivors in rows:
        print(f"{name} | {size} | {named_score:.1%} | {auto_score:.1%} | {survivors}")
    print(f"generated wall-clock time: {generation_time:.6f}s")
    author_time = (
        f"{args.author_time_minutes:.1f} minutes"
        if args.author_time_minutes is not None
        else "not provided"
    )
    print(f"baseline author time: {author_time}")


if __name__ == "__main__":
    main()
