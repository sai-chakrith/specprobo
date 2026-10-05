import subprocess
import sys


def run_command(command: list[str]) -> None:
    print(f"--> Running: {' '.join(command)}")
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        print(f"Error: command failed with exit code {result.returncode}")
        sys.exit(result.returncode)


def check() -> None:
    steps = [
        [sys.executable, "-m", "ruff", "check", "src", "tests"],
        [sys.executable, "-m", "mypy", "src"],
        [sys.executable, "-m", "pytest", "-q"],
        [sys.executable, "-m", "eval.extraction_eval"],
        [sys.executable, "-m", "eval.mutation_eval"],
    ]
    for step in steps:
        run_command(step)
    print("All checks and evaluations passed successfully.")


def main() -> None:
    action = sys.argv[1] if len(sys.argv) > 1 else "check"
    if action == "check":
        check()
    elif action == "lint":
        run_command([sys.executable, "-m", "ruff", "check", "src", "tests"])
        run_command([sys.executable, "-m", "mypy", "src"])
    elif action == "test":
        run_command([sys.executable, "-m", "pytest", "-q"])
    elif action == "eval-extraction":
        run_command([sys.executable, "-m", "eval.extraction_eval"])
    elif action == "eval-mutation":
        run_command([sys.executable, "-m", "eval.mutation_eval"])
    else:
        print(f"Unknown action: {action}")
        sys.exit(1)


if __name__ == "__main__":
    main()
