# Makefile com comandos úteis
.PHONY: install run-backend run-tests

install:
	python -m pip install -r backend/requirements.txt

run-backend:
	# Unix: usa script helper
	./backend/run_dev.sh

run-tests:
	pytest -q
