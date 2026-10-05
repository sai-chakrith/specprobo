.PHONY: lint test demo eval eval-extraction eval-mutation check

lint:
	python -m ruff check src tests
	python -m mypy src

test:
	python -m pytest -q

demo:
	python -m specprobe.demo

eval: eval-mutation

eval-extraction:
	python -m eval.extraction_eval

eval-mutation:
	python -m eval.mutation_eval

check: lint test eval-extraction eval-mutation
