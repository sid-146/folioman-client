# Development & Contributing

This guide explains how to set up the development environment, execute tests, build documentation, and package `folioman-client` for distribution.

---

## Prerequisites

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/) (recommended) or standard `pip`/`venv`

---

## Repository Setup

1. **Clone the repository:**

    ```bash
    git clone https://github.com/sid-146/folioman-client.git
    cd folioman-client
    ```

2. **Install dependencies with `uv`:**
    ```bash
    uv sync
    ```
    This creates an isolated virtual environment in `.venv/` and installs runtime, testing, and documentation packages.

---

## Running the Test Suite

The test suite uses `pytest`, `pytest-asyncio`, and `respx` for mock HTTP responses.

```powershell
uv run pytest
```

To run with verbose output or targeted files:

```powershell
uv run pytest -v tests/test_client.py
```

All 17 tests verify:

- Proactive and reactive JWT token handling
- Concurrency locks
- Resource method parsing and status code mapping
- Serialization and model validation

---

## Building the Package

We use `hatchling` as the build backend. Build both a binary wheel and source distribution (`sdist`):

```powershell
uv build
```

Artifacts are placed into the `dist/` directory:

- `dist/folioman_client-<version>-py3-none-any.whl`
- `dist/folioman_client-<version>.tar.gz`

---

## Documentation Workflow

Documentation is built with **MkDocs Material** and **mkdocstrings**.

### Previewing Documentation Locally

Start a live reload server:

```powershell
uv run mkdocs serve
```

Open `http://127.0.0.1:8000/` in your browser. Changes saved in `docs/` or Python docstrings will automatically refresh in your browser.

### Building Documentation with Strict Validation

To verify all links, navigation entries, and Python docstrings resolve without warnings:

```powershell
uv run mkdocs build --strict
```

---

## Code Quality & Docstring Conventions

When contributing new features or modifying existing public APIs:

1. **Strict Typing**: All function signatures and model attributes must include complete type annotations.
2. **Google-Style Docstrings**: Public classes, methods, models, and exceptions must feature Google-style docstrings (`Args`, `Returns`, `Raises`).
3. **No Credential Leaks**: Never hardcode credentials, real JWTs, or production endpoints in tests, comments, or examples.

---

## CI/CD and Release Workflow

- **CI Documentation Deployment (`docs.yml`)**: Pushes to `main` automatically run `mkdocs gh-deploy` to publish documentation to GitHub Pages at `https://sid-146.github.io/folioman-client/`.
- **PyPI Release (`publish.yml`)**: Publishing a GitHub Release triggers PyPI Trusted Publishing (OIDC) to build distributions and upload to PyPI automatically.
