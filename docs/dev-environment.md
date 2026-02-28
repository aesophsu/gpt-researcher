# Dev Environment: Nix + uv + npm

This project uses a layered setup for reproducible local development:

- Nix: toolchain and versions (Python, uv, Node, npm, git)
- uv: Python dependencies and virtual environment
- npm: NextJS frontend dependencies

## Responsibilities

- Nix layer:
  - Ensures consistent versions for Python/Node/tooling across machines.
  - Defined in `flake.nix`.
- Python layer:
  - Managed by `uv` from root `pyproject.toml` (with fallback to `requirements.txt`).
- Frontend layer:
  - Managed by npm in `frontend/nextjs` using `package-lock.json`.

## First-time setup

1. Enter the repository.
2. Enable direnv once:

```bash
direnv allow
```

3. Install project dependencies:

```bash
make bootstrap
```

## Daily workflow

Start backend:

```bash
make backend-dev
```

Start frontend (new terminal):

```bash
make frontend-dev
```

Open:

- Backend: http://127.0.0.1:8000
- Frontend: http://127.0.0.1:3000

## Useful commands

```bash
make nix-shell      # enter nix develop shell
make deps           # uv sync (with requirements fallback)
make deps-upgrade   # uv lock --upgrade + sync (with fallback)
make dev            # prints two-terminal startup commands
```

## Troubleshooting

### 1) `uv sync` dependency resolution fails

The project Makefile already includes fallback logic:

- Try `uv sync`
- If that fails, fallback to `uv pip install -r requirements.txt`

Run:

```bash
make deps
```

### 2) Frontend dependency issues

Reinstall frontend dependencies:

```bash
cd frontend/nextjs
rm -rf node_modules
npm install
```

### 3) Port conflicts (8000/3000)

- Stop existing processes using those ports, or
- Override host/port in manual startup commands.

## Notes

- This setup intentionally avoids moving all Python/Node dependencies into Nix derivations.
- Keep app dependencies in project lockfiles (`uv.lock` when used, `package-lock.json` for frontend).
