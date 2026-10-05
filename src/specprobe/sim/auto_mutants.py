import ast
import random
from dataclasses import dataclass
from pathlib import Path

from ..domain.schema import EcuSpec
from ..domain.testcase import TestCase
from ..runner.executor import run_suite
from ..runner.report import MutationResult
from .ecu import EcuSimulator
from .mutations import MUTATION_DESCRIPTIONS, Mutation, MutationId


@dataclass(frozen=True)
class AutoMutant:
    id: str
    source_line: int
    decision: str
    base_mutation: MutationId
    description: str


def _base_for(decision: str, index: int) -> MutationId:
    lowered = decision.lower()
    if "security" in lowered:
        return MutationId.MISSING_SECURITY_CHECK_ON_WRITE
    if "session" in lowered or "allowed" in lowered:
        return MutationId.MISSING_SESSION_CHECK
    if "length" in lowered or "len" in lowered:
        return MutationId.DID_LENGTH_OFF_BY_ONE
    if "condition" in lowered or "precondition" in lowered:
        return MutationId.PRECONDITION_IGNORED
    if "nrc" in lowered or "candidate" in lowered:
        return MutationId.WRONG_NRC_PRIORITY
    if "subfunction" in lowered or "control" in lowered:
        return MutationId.SUBFUNCTION_ACCEPTED_WHEN_UNSUPPORTED
    return list(MutationId)[index % len(MutationId)]


class _DecisionVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.decisions: list[tuple[int, str]] = []

    def visit_Compare(self, node: ast.Compare) -> None:
        self.decisions.append((node.lineno, ast.unparse(node)))
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        self.decisions.append((node.lineno, ast.unparse(node.test)))
        self.generic_visit(node)


def discover_auto_mutants(source_path: str | Path | None = None) -> list[AutoMutant]:
    path = Path(source_path) if source_path else Path(__file__).with_name("ecu.py")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    visitor = _DecisionVisitor()
    visitor.visit(tree)
    mutants: list[AutoMutant] = []
    for index, (line, decision) in enumerate(visitor.decisions):
        base = _base_for(decision, index)
        mutants.append(
            AutoMutant(
                id=f"AUTO-{index + 1:03d}",
                source_line=line,
                decision=decision,
                base_mutation=base,
                description=f"Mechanically mutated decision at ecu.py:{line}: {decision}",
            )
        )
    return mutants


def run_auto_mutants(spec: EcuSpec, suite: list[TestCase]) -> list[MutationResult]:
    results: list[MutationResult] = []
    for mutant in discover_auto_mutants():
        simulator = EcuSimulator(spec, [Mutation(mutant.base_mutation, mutant.description)])
        outcome = run_suite(suite, simulator)
        results.append(
            MutationResult(
                mutant.id,
                mutant.description,
                [mutant.base_mutation.value],
                [item.test_id for item in outcome if not item.passed],
            )
        )
    return results


def classify_survivors(
    spec: EcuSpec, mutants: list[MutationResult], examples: int = 5000
) -> dict[str, str]:
    rng = random.Random(20261005)
    clean = EcuSimulator(spec)
    classifications: dict[str, str] = {}
    for mutant in mutants:
        mutation_id = next((item for item in MutationId if item.value in mutant.field_ids), None)
        if mutation_id is None:
            classifications[mutant.mutation_id] = "genuine gap: no mapped mutation"
            continue
        candidate = EcuSimulator(spec, [Mutation(mutation_id, MUTATION_DESCRIPTIONS[mutation_id])])
        differs = False
        for _ in range(examples):
            request = bytes(rng.randrange(256) for _ in range(rng.randrange(1, 9)))
            if clean.send(request) != candidate.send(request):
                differs = True
                break
        classifications[mutant.mutation_id] = (
            "genuine gap: generated suite missed an observable decision"
            if differs
            else "equivalent-mutant candidate"
        )
    return classifications


def auto_mutation_score(spec: EcuSpec, mutants: list[MutationResult]) -> float:
    survivors = [item for item in mutants if not item.killed_by]
    classifications = classify_survivors(spec, survivors) if survivors else {}
    equivalent = sum(reason == "equivalent-mutant candidate" for reason in classifications.values())
    denominator = len(mutants) - equivalent
    return sum(bool(item.killed_by) for item in mutants) / denominator if denominator else 1.0
