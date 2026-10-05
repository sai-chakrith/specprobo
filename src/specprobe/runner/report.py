import json
from dataclasses import dataclass, field

from .executor import TestResult


@dataclass
class MutationResult:
    mutation_id: str
    description: str
    field_ids: list[str]
    killed_by: list[str]
    operator: str = ""
    source_line: int = 0
    original_code: str = ""
    mutated_code: str = ""
    compilable: bool = True
    classification: str = ""


@dataclass
class Report:
    results: list[TestResult]
    mutation_results: list[MutationResult] = field(default_factory=list)

    @property
    def mutation_score(self) -> float:
        if not self.mutation_results:
            return 0.0
        return sum(bool(item.killed_by) for item in self.mutation_results) / len(
            self.mutation_results
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": sum(item.passed for item in self.results),
            "total": len(self.results),
            "results": [item.model_dump(mode="json") for item in self.results],
            "mutation_score": self.mutation_score,
            "mutations": [item.__dict__ for item in self.mutation_results],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def to_markdown(self) -> str:
        lines = [
            "# SpecProbe Report",
            "",
            f"Passed: {sum(item.passed for item in self.results)}/{len(self.results)}",
            f"Mutation score: {self.mutation_score:.1%}",
            "",
            "## Mutations",
            "",
            "| Mutant | Killed by |",
            "| --- | --- |",
        ]
        lines.extend(
            f"| {item.mutation_id} | {', '.join(item.killed_by) or 'undetected'} |"
            for item in self.mutation_results
        )
        return "\n".join(lines)
