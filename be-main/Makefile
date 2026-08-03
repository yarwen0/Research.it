.PHONY: dev
dev:
	python3 main.py

.PHONY: install
install:
	pip install -r requirements-dev.txt

.PHONY: test
test:
	pytest

.PHONY: docker-build
docker-build:
	docker build -t researchit-backend .

.PHONY: docker-run
docker-run:
	docker run --rm -p 8000:8000 --env-file .env researchit-backend

.PHONY: help
help:
	@echo "Available commands:"
	@echo "  make install      - Install runtime and dev dependencies"
	@echo "  make dev          - Run the FastAPI server in development mode"
	@echo "  make test         - Run the pytest test suite"
	@echo "  make docker-build - Build the backend container image"
	@echo "  make docker-run   - Run the backend container on port 8000"
