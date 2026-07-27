# Contributing

Thanks for working on Research.it! This is a monorepo with a Python backend
(`be-main/`) and a Next.js frontend (`fe-main/`).

## Getting set up

- **Backend:** see [`be-main/README.md`](be-main/README.md)
- **Frontend:** see [`fe-main/README.md`](fe-main/README.md)

## Checks to run before pushing

CI runs these on every push and pull request to `main`
(see [`.github/workflows/ci.yml`](.github/workflows/ci.yml)) — run them locally
first:

```bash
# Backend tests
cd be-main
pip install -r requirements-dev.txt
make test

# Frontend lint + tests
cd ../fe-main
pnpm install
pnpm lint
pnpm test
pnpm build
```

## Conventions

- Keep commits small and focused; write imperative subject lines
  (e.g. `fix(arxiv): ...`, `docs: ...`).
- Backend code targets Python 3.10+; frontend uses TypeScript and pnpm.
- Formatting defaults are captured in [`.editorconfig`](.editorconfig).
- Don't commit secrets — copy `.env.example` to `.env` (backend) or
  `.env.local` (frontend) for local configuration.
