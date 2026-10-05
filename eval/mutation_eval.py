from time import perf_counter

from specprobe.demo import build_spec, run_mutations
from specprobe.gen.generator import generate_suite
from specprobe.sim.auto_mutants import auto_mutation_score, classify_survivors, run_auto_mutants
from tests.baseline_suite import build_baseline_suite


def main() -> None:
    spec = build_spec()
    started = perf_counter()
    generated = generate_suite(spec)
    generation_time = perf_counter() - started
    rows: list[tuple[str, int, float, float, str]] = []
    for name, suite in (("baseline", build_baseline_suite()), ("generated", generated)):
        named = run_mutations(spec, suite)
        auto = run_auto_mutants(spec, suite)
        survivors = [item.mutation_id for item in auto if not item.killed_by]
        reasons = classify_survivors(spec, [item for item in auto if not item.killed_by])
        survivor_text = ", ".join(f"{item} ({reasons[item]})" for item in survivors) or "none"
        rows.append(
            (name, len(suite), named.mutation_score, auto_mutation_score(spec, auto), survivor_text)
        )
    print("suite | size | named-mutant score | auto-mutant score | survivors")
    for name, size, named_score, auto_score, survivors in rows:
        print(f"{name} | {size} | {named_score:.1%} | {auto_score:.1%} | {survivors}")
    print(f"generated wall-clock time: {generation_time:.6f}s")
    print("baseline author-time assumption: 4 engineer-hours")


if __name__ == "__main__":
    main()
