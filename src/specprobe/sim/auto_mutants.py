import ast
import copy
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from ..domain.schema import EcuSpec
from ..domain.testcase import TestCase, TraceRef
from ..runner.executor import run_suite
from ..runner.report import MutationResult
from .ecu import EcuSimulator


@dataclass(frozen=True)
class AutoMutant:
    id: str
    operator: str
    source_line: int
    original_code: str
    mutated_code: str
    simulator_type: type[EcuSimulator] | None = field(default=None, repr=False, compare=False)
    compile_error: str | None = None

    @property
    def description(self) -> str:
        return (
            f"{self.operator} at ecu.py:{self.source_line}: "
            f"{self.original_code} -> {self.mutated_code}"
        )


_LAST_MUTANTS: dict[str, AutoMutant] = {}
_NRC_VALUES = frozenset({0x11, 0x12, 0x13, 0x22, 0x24, 0x31, 0x33, 0x35, 0x7E, 0x7F})


def _replacement_code(replacement: Any) -> str:
    operators = {
        ast.Eq: "==",
        ast.NotEq: "!=",
        ast.Lt: "<",
        ast.GtE: ">=",
        ast.LtE: "<=",
        ast.Gt: ">",
        ast.And: "and",
        ast.Or: "or",
    }
    for node_type, text in operators.items():
        if isinstance(replacement, node_type):
            return text
    return ast.unparse(replacement) if isinstance(replacement, ast.AST) else repr(replacement)


def _source_node(tree: ast.AST, line: int, column: int, node_type: type[ast.AST]) -> ast.AST | None:
    return next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, node_type)
            and getattr(node, "lineno", -1) == line
            and getattr(node, "col_offset", -1) == column
        ),
        None,
    )


def _mutate_tree(
    tree: ast.Module,
    line: int,
    column: int,
    node_type: type[ast.AST],
    change: str,
    replacement: Any,
) -> ast.Module:
    mutated = copy.deepcopy(tree)
    target = _source_node(mutated, line, column, node_type)
    if target is None:
        raise ValueError("mutation target disappeared")
    if change == "compare":
        cast(ast.Compare, target).ops[0] = replacement
    elif change == "if":
        cast(ast.If, target).test = replacement
    elif change == "boolop":
        cast(ast.BoolOp, target).op = replacement
    elif change == "constant":
        cast(ast.Constant, target).value = replacement
    elif change == "return":
        cast(ast.Return, target).value = replacement
    ast.fix_missing_locations(mutated)
    return mutated


def _compile(tree: ast.Module, filename: str, name: str) -> type[EcuSimulator]:
    class_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "EcuSimulator"
    )
    class_node.name = name
    class_node.bases = [ast.Name(id="EcuSimulator", ctx=ast.Load())]
    ast.fix_missing_locations(tree)
    namespace = dict(vars(__import__("specprobe.sim.ecu", fromlist=["EcuSimulator"])))
    namespace["__name__"] = "specprobe.sim.generated_mutant"
    exec(compile(tree, filename, "exec"), namespace)
    return cast(type[EcuSimulator], namespace[name])


def _candidate_specs(tree: ast.Module, spec: EcuSpec) -> list[tuple[str, ast.AST, str, Any]]:
    candidates: list[tuple[str, ast.AST, str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            replacements: dict[type[ast.cmpop], ast.cmpop] = {
                ast.Eq: ast.NotEq(),
                ast.NotEq: ast.Eq(),
                ast.Lt: ast.GtE(),
                ast.GtE: ast.Lt(),
                ast.LtE: ast.Gt(),
                ast.Gt: ast.LtE(),
            }
            replacement = next(
                (
                    value
                    for key, value in replacements.items()
                    if isinstance(node.ops[0], key)
                ),
                None,
            )
            if replacement is not None:
                candidates.append(("flip-comparison", node, "compare", replacement))
            has_len_call = any(
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id == "len"
                for child in ast.walk(node)
            )
            if has_len_call:
                for child in ast.walk(node):
                    if isinstance(child, ast.Constant) and isinstance(child.value, int):
                        candidates.append(("length-off-by-one", child, "constant", child.value + 1))
                        candidates.append(
                            ("length-off-by-one", child, "constant", max(0, child.value - 1))
                        )
        elif isinstance(node, ast.If):
            candidates.extend(
                (
                    ("if-test-true", node, "if", ast.Constant(True)),
                    ("if-test-false", node, "if", ast.Constant(False)),
                )
            )
        elif isinstance(node, ast.BoolOp):
            bool_replacement = ast.Or() if isinstance(node.op, ast.And) else ast.And()
            candidates.append(("swap-boolean-operator", node, "boolop", bool_replacement))
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, int)
            and node.value in _NRC_VALUES
        ):
            values = [value for value in spec.nrc_priority if value != node.value]
            if values:
                candidates.append(("replace-nrc", node, "constant", values[0]))
        elif isinstance(node, ast.Return) and isinstance(node.value, ast.Call):
            if isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "_negative":
                candidates.append(("delete-nrc-return", node, "return", ast.Constant(None)))
    return candidates


def discover_auto_mutants(
    source_path: str | Path | None = None, spec: EcuSpec | None = None
) -> list[AutoMutant]:
    path = Path(source_path) if source_path else Path(__file__).with_name("ecu.py")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    effective_spec = spec or EcuSpec.model_construct(nrc_priority=list(_NRC_VALUES))
    mutants: list[AutoMutant] = []
    for index, (operator, node, change, replacement) in enumerate(
        _candidate_specs(tree, effective_spec), 1
    ):
        located_node = cast(Any, node)
        source_line = int(located_node.lineno)
        source_column = int(located_node.col_offset)
        original = ast.unparse(node)
        mutated_code = _replacement_code(replacement)
        try:
            mutated_tree = _mutate_tree(
                tree, source_line, source_column, type(node), change, replacement
            )
            mutant_type = _compile(mutated_tree, str(path), f"EcuSimulatorMutant{index}")
            compile_error = None
        except (SyntaxError, TypeError, ValueError) as error:
            mutant_type = None
            compile_error = str(error)
        mutants.append(
            AutoMutant(
                f"AUTO-{index:04d}",
                operator,
                source_line,
                original,
                mutated_code,
                mutant_type,
                compile_error,
            )
        )
    return mutants


def run_auto_mutants(spec: EcuSpec, suite: list[TestCase]) -> list[MutationResult]:
    global _LAST_MUTANTS
    discovered = discover_auto_mutants(spec=spec)
    _LAST_MUTANTS = {mutant.id: mutant for mutant in discovered}
    results: list[MutationResult] = []
    for mutant in discovered:
        killed_by: list[str] = []
        if mutant.simulator_type is not None:
            simulator = mutant.simulator_type(spec)
            for case in suite:
                try:
                    outcome = run_suite([case], simulator)
                    if not outcome[0].passed:
                        killed_by.append(case.id)
                except Exception:
                    killed_by.append(case.id)
        results.append(
            MutationResult(
                mutant.id,
                mutant.description,
                [mutant.operator],
                killed_by,
                mutant.operator,
                mutant.source_line,
                mutant.original_code,
                mutant.mutated_code,
                mutant.simulator_type is not None,
            )
        )
    return results


def _requests(spec: EcuSpec) -> list[bytes]:
    requests = [
        b"",
        b"\x99",
        b"\x22",
        b"\x2e\x10\x00",
        b"\x27\x02\x00\x00",
        b"\x31\x01\x20\x00",
    ]
    requests.extend(bytes((0x10, session.id)) for session in spec.sessions)
    requests.extend(bytes((0x22, did.did >> 8, did.did & 0xFF)) for did in spec.dids)
    for did in spec.dids:
        requests.append(
            bytes((0x2E, did.did >> 8, did.did & 0xFF)) + bytes(did.length_bytes)
        )
    for routine in spec.routines:
        for control in routine.control_types:
            request = bytes((0x31, control, routine.rid >> 8, routine.rid & 0xFF))
            requests.append(request + bytes(routine.parameter_lengths.get(control, 0)))
    requests.extend((b"\x27\x01", b"\x27\x02\xff\x5b", b"\x3e\x00", b"\x3e\x80", b"\x3e\x01"))
    return requests


def _sequences(spec: EcuSpec, count: int) -> list[list[tuple[dict[str, object], bytes]]]:
    rng = random.Random(20261005)
    requests = _requests(spec)
    signals = {
        condition.signal or "signal": condition.value
        for did in spec.dids
        for condition in did.preconditions
        if condition.kind == "signal"
    }
    return [
        [
            (dict(signals) if rng.randrange(3) else {}, rng.choice(requests))
            for _ in range(rng.randint(1, 8))
        ]
        for _ in range(count)
    ]


def classify_survivors(
    spec: EcuSpec, mutants: list[MutationResult], examples: int = 5000
) -> dict[str, str]:
    classifications: dict[str, str] = {}
    for result in mutants:
        mutant = _LAST_MUTANTS.get(result.mutation_id)
        if mutant is None or mutant.simulator_type is None:
            classifications[result.mutation_id] = "genuine gap: uncompilable or unavailable mutant"
            continue
        differs = False
        for sequence in _sequences(spec, max(5000, examples)):
            clean = EcuSimulator(spec)
            candidate = mutant.simulator_type(spec)
            for environment, request in sequence:
                clean.set_environment(environment)
                candidate.set_environment(environment)
                try:
                    clean_response = clean.send(request)
                    candidate_response = candidate.send(request)
                except Exception:
                    differs = True
                    break
                if clean_response != candidate_response:
                    differs = True
                    break
            if differs:
                break
        classification = (
            "genuine gap: observable difference"
            if differs
            else "equivalent-mutant candidate"
        )
        classifications[result.mutation_id] = classification
        result.classification = classification
    return classifications


def add_general_survivor_rules(
    spec: EcuSpec, suite: list[TestCase], survivors: list[MutationResult]
) -> list[str]:
    """Add broad operator-family probes, never a case for one specific mutant."""
    rules = sorted(
        {item.operator for item in survivors if item.classification.startswith("genuine gap")}
    )
    if not rules:
        return []
    requests = _requests(spec)
    for rule in rules:
        for index, request in enumerate(requests):
            clean = EcuSimulator(spec)
            expected = clean.send(request)
            suite.append(
                TestCase(
                    id=f"survivor-rule-{rule}-{index}",
                    trace_to=[TraceRef(field_id=f"generated.{rule}", page=0)],
                    preconditions={},
                    setup_steps=[],
                    steps=[request],
                    environment={},
                    expected=expected,
                    tags=["generated", "survivor-rule", rule],
                )
            )
    return rules


def auto_mutation_score(spec: EcuSpec, mutants: list[MutationResult]) -> float:
    compilable = [item for item in mutants if item.compilable]
    survivors = [item for item in compilable if not item.killed_by]
    classifications = classify_survivors(spec, survivors) if survivors else {}
    equivalent = sum(
        reason == "equivalent-mutant candidate" for reason in classifications.values()
    )
    denominator = len(compilable) - equivalent
    return sum(bool(item.killed_by) for item in compilable) / denominator if denominator else 1.0
