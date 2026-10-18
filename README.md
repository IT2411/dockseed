# Dockseed

**Dockseed** is a deterministic Python developer tool that inspects an existing Python project and generates a project-specific, best-practice `Dockerfile` and `.dockerignore` automatically.

## Key Features

- **Evidence-Based Detection:** Inspects `pyproject.toml`, `requirements.txt`, `Pipfile`, `.python-version`, `.tool-versions`, and `runtime.txt` to resolve compatible Python versions (`3.10`–`3.14`).
- **Modern Package Manager Support:** Automatically configures layer-cached dependency installation for `pip`, `uv`, `Poetry`, `PDM`, `Hatch`, and `Pipenv`.
- **Safe AST Static Analysis:** Discovers application entry points (`FastAPI`, `Flask`, `Django`, `Streamlit`, `Gradio`, `Celery`, CLI scripts, and standalone scripts) using Python's built-in `ast` module—never importing or executing project code.
- **Native System Dependency Heuristics:** Detects packages requiring C extensions or shared libraries (`psycopg2`, `mysqlclient`, `opencv-python`, `pyaudio`, `git+https`, etc.) and injects clean `apt-get` layers.
- **Secure & Production-Minded Defaults:** Generates single-stage `python:3.x-slim` images running as an unprivileged `appuser`, using JSON exec-form `CMD` arrays for proper `SIGTERM` signal handling, and excluding `.env` secrets and virtual environments.
- **CI/CD & Headless Ready:** Deterministic output, explicit CLI override flags, and strict exit codes.

---

## Installation

~~~bash
pip install dockseed
~~~

Or run directly with `uvx` or `pipx`:

~~~bash
uvx dockseed scan
~~~

---

## CLI Usage

### 1. Analyze a Project (`dockseed scan`)

Inspect a project without modifying any files:

~~~bash
dockseed scan
dockseed scan ./my-project
dockseed scan --format json
~~~

### 2. Generate Configuration (`dockseed init`)

Generate a `Dockerfile` and `.dockerignore`:

~~~bash
dockseed init
dockseed init --dry-run
dockseed init --yes
dockseed init --overwrite
dockseed init --no-comments
~~~

Bypass ambiguity prompts in CI/CD pipelines using explicit override flags:

~~~bash
dockseed init --yes \
  --python 3.12 \
  --package-manager uv \
  --entrypoint "app.main:app" \
  --port 8000
~~~

### 3. Validate Configuration (`dockseed check`)

Validate an existing `Dockerfile` and `.dockerignore` statically, or perform an opt-in container build check:

~~~bash
dockseed check
dockseed check --build
dockseed check --build --runtime podman
~~~

---

## Python API

Dockseed's scanning, generation, and validation engine can be used directly from Python:

~~~python
from pathlib import Path
from dockseed import (
    scan_project,
    generate_dockerfile,
    generate_dockerignore,
    validate_dockerfile,
)

model = scan_project(Path("."))
dockerfile = generate_dockerfile(model, include_comments=True)
dockerignore = generate_dockerignore(model)

report = validate_dockerfile(dockerfile.content, model, dockerignore.content)
if report.is_valid:
    print(dockerfile.content)
~~~

---

## Exit Codes

| Exit Code | Constant | Meaning |
| :--- | :--- | :--- |
| `0` | `SUCCESS` | Operation succeeded. |
| `1` | `GENERAL_ERROR` | Unexpected runtime or I/O error. |
| `2` | `VALIDATION_FAILED` | Static/build validation failed, or containerization blocker detected. |
| `3` | `AMBIGUITY_UNRESOLVED` | Unresolved critical ambiguity in non-interactive (`--yes` or non-TTY) mode. |
| `4` | `OVERWRITE_BLOCKED` | Target `Dockerfile` already exists and `--overwrite` was not passed. |

---

## License

MIT
