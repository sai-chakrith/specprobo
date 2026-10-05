from pathlib import Path

from specprobe.data_loader import load_spec

ROOT = Path(__file__).parents[1]


def test_synthetic_specs_are_rich_and_differently_laid_out() -> None:
    oem_a = load_spec(ROOT / "data" / "synthetic" / "ground_truth" / "oem_a.json")
    oem_b = load_spec(ROOT / "data" / "synthetic" / "ground_truth" / "oem_b.json")
    assert len(oem_a.dids) >= 10 and len(oem_b.dids) >= 10
    assert len(oem_a.services) >= 4 and len(oem_b.services) >= 4
    assert len(oem_a.routines) >= 3 and len(oem_b.routines) >= 3
    assert sum(len(did.preconditions) for did in oem_a.dids) >= 6
    assert sum(len(did.preconditions) for did in oem_b.dids) >= 6
    assert [session.id for session in oem_a.sessions] != [session.id for session in oem_b.sessions]
    assert [level.level for level in oem_a.security_levels] != [
        level.level for level in oem_b.security_levels
    ]
