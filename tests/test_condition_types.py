import pytest

from specprobe.demo import build_spec
from specprobe.domain.schema import Precondition
from specprobe.rules.oracle import State, _condition_holds
from specprobe.sim.ecu import EcuSimulator


@pytest.mark.parametrize("op,value,actual", [("==", True, 1), ("<", 14, False)])
def test_condition_comparison_does_not_coerce_boolean_and_numeric_types(op, value, actual):
    condition = Precondition(
        kind="signal", signal="signal", op=op, value=value, source_text="typed condition"
    )
    simulator = EcuSimulator(build_spec())
    simulator.set_environment({"signal": actual})
    assert not _condition_holds(condition, State(1), {"signal": actual})
    assert not simulator._conditions_hold([condition])
