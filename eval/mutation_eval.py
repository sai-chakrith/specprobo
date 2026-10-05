from time import perf_counter

from specprobe.demo import build_spec, run_mutations
from specprobe.domain.testcase import TestCase, TraceRef
from specprobe.gen.generator import generate_suite
from specprobe.rules.oracle import expected_response


def main() -> None:
    spec = build_spec()
    request = b"\x22\xff\xff"
    baseline = [
        TestCase(
            id="baseline-unknown-did",
            trace_to=[TraceRef(field_id="dids", page=1)],
            steps=[request],
            expected=expected_response(spec, 1, 0, {}, request).bytes,
            preconditions={},
            tags=["baseline"],
        )
    ]
    started = perf_counter()
    generated = generate_suite(spec)
    elapsed = perf_counter() - started
    baseline_report = run_mutations(spec, baseline)
    generated_report = run_mutations(spec, generated)
    print(f"baseline mutation score: {baseline_report.mutation_score:.1%}")
    print(f"generated mutation score: {generated_report.mutation_score:.1%}")
    print(f"generation time: {elapsed:.6f}s")


if __name__ == "__main__":
    main()
