.PHONY: dev
dev:
	python3 main.py

.PHONY: install
install:
	pip install -r requirements-dev.txt

.PHONY: test
test:
	pytest

.PHONY: help
help:
	@echo "Available commands:"
	@echo "  make install - Install runtime and dev dependencies"
	@echo "  make dev     - Run the FastAPI server in development mode"
	@echo "  make test    - Run the pytest test suite"
