.PHONY: lint test demo eval

lint:
	python -m ruff check src tests
	python -m mypy src

test:
	python -m pytest -q

demo:
	python -m specprobe.demo

eval:
	python -m eval.mutation_eval
