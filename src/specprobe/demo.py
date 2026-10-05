from specprobe.domain.schema import DataIdentifier, EcuSpec, SecurityLevel, Service, Session, Timing
from specprobe.gen.generator import generate_suite
from specprobe.runner.executor import run_suite
from specprobe.sim.ecu import EcuSimulator
from specprobe.sim.mutations import MutationId, apply_mutations
from specprobe.sim.transport import InMemoryTransport


def build_spec() -> EcuSpec:
    return EcuSpec(
        ecu_name="SYNTH-ECU", oem="OEM-A", version="1",
        sessions=[Session(id=1, name="default"), Session(id=3, name="extended")],
        security_levels=[SecurityLevel(level=0, name="locked"), SecurityLevel(level=1, name="level1")],
        services=[Service(sid=0x22, name="ReadDataByIdentifier"), Service(sid=0x2E, name="WriteDataByIdentifier")],
        dids=[DataIdentifier(did=0x1001, name="VehicleName", length_bytes=4, encoding="ascii", read_sessions=[1, 3], write_sessions=[3], write_security=1)],
        routines=[], timing=Timing(p2_ms=50, p2_star_ms=5000, s3_ms=5000),
        nrc_priority=[0x13, 0x12, 0x7F, 0x7E, 0x33, 0x31, 0x22],
    )


def main() -> None:
    spec = build_spec()
    suite = generate_suite(spec)
    clean = EcuSimulator(spec)
    clean_results = run_suite(suite, InMemoryTransport(clean))
    mutant = EcuSimulator(spec)
    apply_mutations(mutant, [type("WrongNrc", (), {"id": MutationId.WRONG_NRC})()])
    mutant_results = run_suite(suite, InMemoryTransport(mutant))
    detected = sum(not result.passed for result in mutant_results)
    print(f"clean: {sum(result.passed for result in clean_results)}/{len(clean_results)} passed")
    print(f"mutation score: {100 * detected / len(mutant_results):.1f}%")


if __name__ == "__main__":
    main()
