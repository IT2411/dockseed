# Dockseed — Project Specification

**Version:** 0.1.0 (planned)  
**Status:** Specification / pre-development  
**Distribution:** PyPI  
**Package name:** `dockseed`  
**Import package:** `dockseed`  
**CLI command:** `dockseed`  
**Initial language:** Python  
**Initial output:** Dockerfile, `.dockerignore`  
**Python support:** Python 3.10–3.14

---

## 1. Project Overview

### 1.1 Purpose

Dockseed is a Python developer tool that inspects an existing Python project and generates a project-specific, best-practice Dockerfile and `.dockerignore` automatically.

The user should not need to understand Dockerfile syntax, manually identify dependencies, or provide configuration details that can be reliably inferred from the project.

Dockseed inspects project files, identifies the application's runtime and native system requirements, infers how the application starts, and generates container configuration using conservative, reproducible, and secure defaults.

When critical information cannot be determined confidently, Dockseed asks a targeted question (or requires explicit CLI override flags in headless environments) instead of silently generating an incorrect configuration.

### 1.2 Problem Statement

Developers frequently need to containerize existing projects but encounter several obstacles:

- Determining which Python version the project requires.
- Identifying the correct dependency installation procedure and optimizing Docker layer caching.
- Distinguishing development dependencies from runtime dependencies.
- Discovering the application entry point and verifying that production web servers (e.g., `uvicorn`, `gunicorn`) are actually declared.
- Selecting an appropriate base image and configuring non-root execution.
- Identifying required native system dependencies (e.g., `libpq-dev`, `gcc`).
- Handling projects that use Poetry, pip, uv, PDM, Hatch, Pipenv, or standard PEP 621 metadata.
- Detecting uncontainerizable dependencies such as out-of-context local path references or private SSH Git URLs.
- Avoiding accidental inclusion of virtual environments, credentials, and development artifacts.

Existing generic templates cannot reliably account for all these differences.

Dockseed addresses this problem through static project inspection, deterministic inference, reusable templates, and validation.

### 1.3 Goals

The initial release must:

1. Scan a Python project and produce a structured, evidence-based analysis.
2. Detect common Python project manifests, lockfiles, and dependency managers.
3. Infer Python version requirements, native system dependencies, and application startup commands when possible.
4. Generate a readable, layer-cached, non-root Dockerfile with explanatory inline comments.
5. Generate a suitable, conservative `.dockerignore` file.
6. Explain important assumptions, missing production servers, and unresolved ambiguities.
7. Preserve existing user files unless explicitly authorized to overwrite them.
8. Operate locally without requiring an external AI service.
9. Provide a CLI (supporting both interactive and headless CI/CD workflows) and a reusable Python API.
10. Be testable, extensible, and suitable for distribution through PyPI.

### 1.4 Non-goals for v1

The first release will not:

- Generate Docker Compose files.
- Build or publish container images itself (outside of optional validation checks).
- Automatically deploy applications.
- Support Node.js, Go, Java, or other non-Python languages.
- Guarantee production readiness for every complex or non-standard project.
- Install missing dependencies into the host environment.
- Require an LLM or transmit project files to external services.
- Reproduce the complete host operating system inside a container.

Compose generation, multi-stage build optimizations, and additional language detectors will be considered for later releases.

---

## 2. Target Users

Dockseed is intended for:

- Python developers who have never written a Dockerfile.
- Developers who want a quick, best-practice starting point for an existing project.
- Students and contributors working with unfamiliar repositories.
- Developers using virtual environments and modern Python package managers (`uv`, `Poetry`, `PDM`, etc.).
- Teams that want a consistent baseline for containerizing Python services and background workers.
- CI/CD pipelines and developers needing to identify configuration gaps before containerization.

---

## 3. Core Workflow

The standard workflow is:

~~~~bash
cd my-python-project

dockseed scan
dockseed init
~~~~

The scanning command reports the detected project characteristics without modifying files.

The initialization command generates the Dockerfile and supporting `.dockerignore` file.

If the project is sufficiently clear, generation proceeds automatically using conservative defaults. If essential information is ambiguous, Dockseed asks only the questions needed to proceed (or accepts explicit CLI flags).

Example interaction:

~~~~text
$ dockseed init

Dockseed — Python Project Analyzer

Project root: /home/user/my-api

Detected:
  Language: Python
  Python requirement: >=3.11,<3.14 (Resolved: 3.12)
  Package manager: Poetry (poetry.lock)
  Framework: FastAPI
  Entry point: app.main:app
  System packages: libpq-dev, gcc (required by psycopg2)
  Application port: 8000

Configuration:
  Base image: python:3.12-slim
  Runtime user: appuser (non-root)
  Startup command: ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

Files to create:
  Dockerfile
  .dockerignore

Proceed? [Y/n] y

Dockerfile created.
.dockerignore created.

Review the generated files before building the image.
~~~~

This output is illustrative. Dockseed must not claim a detection succeeded unless the relevant evidence exists.

---

## 4. Functional Requirements

### FR-01: Project discovery

Dockseed must:

- Accept an optional project path, defaulting to the current working directory.
- Identify common Python project manifests and lockfiles.
- Recognize existing Dockerfiles and `.dockerignore` files.
- Detect nested project roots when relevant.
- Avoid scanning `.git`, virtual environments (`.venv`, `venv`), build outputs, cache directories, and other irrelevant directories by default.
- Support a deterministic scan report in both human-readable and JSON formats.

### FR-02: Python version detection

Dockseed should inspect, in order of reliability:

1. Explicit CLI override (`--python`).
2. `requires-python` in `pyproject.toml`.
3. Tool-specific Python constraints, such as Poetry's `tool.poetry.dependencies.python` or `Pipfile` `python_version`.
4. Explicit `.python-version` or `.tool-versions` files.
5. Other recognized runtime-version configuration files (e.g., `runtime.txt`).
6. The active interpreter as a fallback.

The active interpreter must not override an explicit project requirement.

If the project permits multiple Python versions (e.g., `>=3.10`), Dockseed should choose the latest stable, compatible version within the supported range (3.10–3.14) using documented selection rules.

If version information is unavailable, it may use the active interpreter's major and minor version as a provisional default, provided that the assumption is reported.

Dockseed must not silently choose an incompatible Python version.

### FR-03: Dependency manager and blocker detection

Initial support must cover:

- `pip` with `requirements.txt` (and common variants like `requirements/prod.txt`).
- `pip` with standard PEP 621 `pyproject.toml` project metadata.
- `Poetry` (`pyproject.toml` + `poetry.lock`).
- `uv` (`pyproject.toml` + `uv.lock`).
- `PDM` (`pyproject.toml` + `pdm.lock`).
- `Hatch` (`pyproject.toml` / `hatch.toml`).
- `Pipenv` (`Pipfile` + `Pipfile.lock`).

Detection must use manifest contents and lockfiles, not filenames alone.

If several package managers appear in the same project, Dockseed should identify the likely authoritative manager (prioritizing active lockfiles) and report conflicting evidence. It must not automatically combine dependency installation commands from different package managers.

Additionally, Dockseed must scan declared dependencies for containerization blockers:

- Local path dependencies pointing outside the project build context (e.g., `../shared-lib`).
- Private Git dependencies requiring SSH keys (`git+ssh://...`) or unconfigured credentials.

When found, these must be flagged as high-priority warnings or blockers during `scan` and `init`.

### FR-04: Framework and workload detection

The initial detector should recognize common application frameworks, web servers, and background workers, including:

- FastAPI.
- Flask.
- Django.
- Streamlit.
- Gradio.
- Celery / RQ / Dramatiq (background workers).
- Generic Python command-line applications (`click`, `typer`, `argparse`).
- Generic standalone Python scripts.

Framework detection must use declared dependencies, project configuration, application structure, and static source-code inspection via Python's built-in `ast` module.

The presence of a framework dependency alone does not prove that the application uses that framework as its primary entry point.

### FR-05: Entry-point and server inference

Dockseed must attempt to determine the correct startup command using:

1. Explicit CLI override (`--entrypoint`).
2. Explicit project scripts (`[project.scripts]`, `[tool.poetry.scripts]`) or entry-point metadata.
3. Recognized framework configuration (e.g., Django's `manage.py` and `WSGI_APPLICATION`/`ASGI_APPLICATION`, Streamlit entry files).
4. Common application module patterns (`app/main.py`, `src/<pkg>/main.py`, `wsgi.py`, `asgi.py`).
5. Static source-code inspection using the `ast` module (identifying `FastAPI()`, `Flask(__name__)`, `Celery()`, or `if __name__ == "__main__":` blocks without tripped regexes on comments or strings).
6. A targeted user question when multiple plausible candidates remain (e.g., both a web API and a Celery worker, or multiple scripts).

Dockseed must never import arbitrary project modules to discover entry points, as importing project code may execute side effects or access external resources.

For web applications, Dockseed must cross-check that the inferred production server (`uvicorn`, `gunicorn`, `granian`, `daphne`) is actually declared in the project's runtime dependencies:

- If present, generate the production server startup command.
- If missing (e.g., `Flask` is installed without `gunicorn`), emit a prominent warning and either fall back to the framework's built-in runner (e.g., `python -m flask run --host=0.0.0.0`) or prompt the user.

For Django applications, Dockseed should detect static file configuration and include a `python manage.py collectstatic --noinput` step (or an annotated, commented-out instruction if environment variables are required at build time).

For CLI applications, it must distinguish an installed console-script entry point from a standalone script.

### FR-06: Native system dependency heuristics

Many Python packages require C extensions or native shared libraries on Debian `-slim` base images. Dockseed must include a deterministic heuristic mapping for common Python packages to their Debian `apt-get` equivalents:

- `psycopg2` (non-binary) -> `libpq-dev`, `gcc` (and emit a suggestion regarding `psycopg2-binary`).
- `mysqlclient` -> `default-libmysqlclient-dev`, `build-essential`, `pkg-config`.
- `opencv-python` (non-headless) -> `libgl1`, `libglib2.0-0`.
- `pillow` -> `libjpeg62-turbo-dev`, `zlib1g-dev` (when building from source) or runtime equivalents.
- `cryptography` / `cffi` (when wheels are unavailable) -> `gcc`, `libffi-dev`.
- `pyaudio` -> `portaudio19-dev`, `gcc`.
- `git+https://...` dependencies -> `git`.

When detected, Dockseed must record the evidence and inject a clean `apt-get update && apt-get install -y --no-install-recommends ... && rm -rf /var/lib/apt/lists/*` layer prior to dependency installation.

### FR-07: Environment inspection

Dockseed may optionally inspect the active Python environment to help infer missing information.

It may collect:

- Python executable and version.
- Environment manager and virtual-environment location.
- Installed package names and versions.
- Differences between declared and installed dependencies (e.g., `uvicorn` installed locally in `.venv` but missing from `requirements.txt`).

Environment inspection must not treat every installed package as a runtime dependency. Declared dependencies and lockfiles always take precedence over incidental packages in the environment.

The scan must never copy the local virtual environment into the generated container.

### FR-08: Dockerfile generation

The generator must follow modern Docker best practices:

- Select an appropriate official Python base image (e.g., `python:3.12-slim`).
- Set standard Python container environment variables (`PYTHONDONTWRITEBYTECODE=1`, `PYTHONUNBUFFERED=1`, `PIP_NO_CACHE_DIR=1`, `UV_NO_CACHE=1`).
- Set a clean working directory (e.g., `/app`).
- Install detected native system dependencies via `apt-get` and clean up apt caches in the same `RUN` layer.
- Optimize layer caching by copying only dependency manifests (`requirements.txt`, `pyproject.toml`, lockfiles) and installing dependencies *before* copying the rest of the application source code.
  - Handle package-manager nuances appropriately (e.g., `uv sync --frozen --no-install-project`, `poetry install --no-root --only main`, or two-step `pip` installation when a project installs itself as a package).
- Copy application source files with appropriate ownership.
- Create and switch to an unprivileged, non-root user (e.g., `appuser`) before runtime execution.
- Expose a port (`EXPOSE`) when a web-service port is confidently detected or specified.
- Configure the startup command using the JSON array **exec form** (e.g., `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]`) to ensure proper `SIGTERM` signal propagation.
- Include brief, educational inline comments (controllable via `--comments / --no-comments`, enabled by default) explaining *why* key instructions were chosen based on detected evidence.
- Avoid embedding secrets or host-specific paths.

The generator will prefer optimized single-stage builds for v1. Multi-stage builds can be introduced when justified by a supported use case.

### FR-09: `.dockerignore` generation

Dockseed must generate a conservative `.dockerignore` containing appropriate exclusions for:

- Git metadata (`.git`, `.gitignore`).
- Python bytecode and cache directories (`__pycache__/`, `*.py[cod]`).
- Virtual environments (`.venv/`, `venv/`, `env/`).
- Test, lint, and type-check caches (`.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`, `.coverage`, `htmlcov/`).
- Build and distribution artifacts (`build/`, `dist/`, `*.egg-info/`).
- Local environment files containing secrets (`.env`, `.env.*`, keeping `.env.example` if needed).
- IDE configurations (`.vscode/`, `.idea/`).

The generated rules must not exclude files required by the application or package manager (such as `README.md` if referenced in `pyproject.toml`). An existing `.dockerignore` must not be replaced automatically.

### FR-10: Safe file operations

Dockseed must:

- Preview planned file changes.
- Avoid overwriting existing files by default.
- Support explicit overwrite authorization (`--overwrite`).
- Never delete project files automatically.
- Write files atomically where practical.
- Produce actionable errors when a directory is inaccessible or a file cannot be written.

### FR-11: Validation

Dockseed must validate its own generated output before writing it, and support validating existing Dockerfiles via `dockseed check`.

Static validation must include:

- Dockerfile structural and required instruction checks (`FROM`, `WORKDIR`, `CMD`/`ENTRYPOINT`).
- Exec-form validation for startup commands.
- Non-root user check (warning if running as `root`).
- Startup command consistency (verifying the runner binary matches declared dependencies).
- Dependency installation consistency (verifying copied manifest files actually exist in the project).
- Base-image version consistency against project Python constraints.
- `.dockerignore` sanity checks (verifying `.env` and virtual environments are excluded, and required manifests/source directories are not accidentally ignored).

An optional build-validation mode (`--build`) may invoke an installed container CLI (`docker`, `podman`, or `nerdctl`). A successful static validation must never be reported as proof that the image builds or that the application works at runtime.

---

## 5. CLI Specification

The following commands define the planned public interface.

### `dockseed scan`

Analyze a project without writing files.

~~~~bash
dockseed scan
dockseed scan ./my-project
dockseed scan --format json
~~~~

Expected behavior:

- Discover project metadata and environment discrepancies.
- Report detections, supporting evidence, and confidence levels.
- Identify missing information and containerization blockers (e.g., out-of-context path dependencies).
- Show warnings about conflicting configurations.

### `dockseed init`

Generate the initial container configuration.

~~~~bash
dockseed init
dockseed init --path ./my-project
dockseed init --dry-run
dockseed init --yes
dockseed init --overwrite
dockseed init --no-comments
dockseed init --python 3.12 --package-manager uv --entrypoint "app.main:app" --port 8000
~~~~

Rules:

- Default behavior includes a preview and confirmation prompt.
- `--dry-run` prints planned changes and generated file contents without writing files.
- `--yes` accepts safe defaults and skips the confirmation prompt. If an unresolved critical ambiguity exists when `--yes` is passed (or when `sys.stdin.isatty()` is `False`), Dockseed must not hang waiting for input; it must exit immediately with exit code `3` and print the exact CLI override flags needed to resolve the ambiguity.
- `--overwrite` explicitly authorizes replacement of targeted existing output files (`Dockerfile`, `.dockerignore`).
- `--comments / --no-comments` toggles explanatory inline comments in the generated Dockerfile (default: `--comments`).
- Explicit override flags (`--python`, `--package-manager`, `--entrypoint`, `--port`) allow users and CI pipelines to bypass ambiguity prompts deterministically.

### `dockseed check`

Validate an existing Dockerfile or the generated configuration.

~~~~bash
dockseed check
dockseed check ./my-project
dockseed check --build
dockseed check --build --runtime podman
~~~~

Rules:

- Performs static validation against the project model and `.dockerignore`.
- `--build` performs an opt-in container image build test.
- `--runtime <docker|podman|nerdctl>` selects the container engine (auto-detecting from `PATH` in that order if omitted). Fails with an actionable message if no supported container CLI is available.

### Exit Codes

To support scripting and CI/CD automation, the CLI must adhere to strict exit codes:

- `0`: Success.
- `1`: General, unexpected, or unhandled runtime error (e.g., I/O permission error).
- `2`: Validation failed (`dockseed check`), or project is unsupported/invalid.
- `3`: Unresolved critical ambiguity in non-interactive mode (`--yes` or non-TTY).
- `4`: File overwrite blocked (target files already exist and `--overwrite` was not provided).

### Future commands

The following commands are deferred until post-v1:

~~~~text
dockseed diff
dockseed compose
dockseed doctor
~~~~

These must not be presented as supported in v1.

---

## 6. Detection and Inference Engine

### 6.1 Architecture

Dockseed uses a staged pipeline:

~~~~text
Project directory + CLI overrides
       |
       v
File discovery
       |
       v
Manifest & lockfile parsing
       |
       v
Python/runtime & native dependency detection
       |
       v
AST-based framework and entry-point detection
       |
       v
Optional environment cross-check
       |
       v
Normalized project model
       |
       v
Ambiguity resolution (CLI prompt or fail-fast in headless mode)
       |
       v
Dockerfile and .dockerignore generation
       |
       v
Static validation
       |
       v
Preview and atomic write
~~~~

Each stage must be independently testable.

### 6.2 Evidence-based inference

Every important inference must record:

- The detected value.
- The evidence supporting it.
- The detector that produced it.
- Its confidence level (`HIGH`, `MEDIUM`, `LOW`).
- Any unresolved conflicts.

For example:

~~~~text
Entry point: app.main:app
Confidence: HIGH
Evidence:
  - FastAPI and uvicorn dependencies declared in pyproject.toml
  - FastAPI application instance 'app' found via AST in app/main.py
  - No conflicting application candidates
~~~~

Confidence levels must follow documented rules rather than arbitrary numerical scores:

- `HIGH`: Direct, unambiguous evidence (e.g., explicit lockfile, explicit CLI override, single entry point verified via AST).
- `MEDIUM`: Multiple supporting clues with minor uncertainty (e.g., conventional filename match, multiple compatible Python versions).
- `LOW`: Fallback or weak inference (e.g., active interpreter fallback when no Python constraint is declared).

### 6.3 Ambiguity resolution

Dockseed must ask a question only when the uncertainty affects the correctness of the generated file and has not been resolved via CLI override flags.

Examples include:

- Multiple possible application entry points (e.g., API vs. worker, or multiple scripts).
- Conflicting Python version declarations across manifests.
- Several plausible package managers with competing lockfiles.
- No reliable startup command detected.
- Missing production WSGI/ASGI server for a detected web framework.

Questions must be concise, include the available choices, and indicate the corresponding CLI flag for future non-interactive runs. The tool must never ask the user to provide information that can already be determined reliably from the project.

### 6.4 Determinism

Given the same project contents, tool version, and options, Dockseed must produce the exact same output.

It must not depend on:

- Unordered filesystem traversal (all directory listings and set outputs must be sorted).
- Random template selection.
- External AI responses.
- Undocumented heuristics that change between runs.

Generated timestamps must be omitted unless explicitly requested.

---

## 7. Data Model

The internal representation must be strictly typed, using `Enum` types for finite states, and remain independent of Dockerfile formatting.

A conceptual model:

~~~~python
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class PackageManager(str, Enum):
    PIP = "pip"
    POETRY = "poetry"
    UV = "uv"
    PDM = "pdm"
    HATCH = "hatch"
    PIPENV = "pipenv"


class Framework(str, Enum):
    FASTAPI = "fastapi"
    FLASK = "flask"
    DJANGO = "django"
    STREAMLIT = "streamlit"
    GRADIO = "gradio"
    CELERY = "celery"
    CLI = "cli"
    SCRIPT = "script"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Evidence:
    source: str
    detector: str
    description: str
    confidence: ConfidenceLevel


@dataclass
class Detection[T]:
    value: T | None
    confidence: ConfidenceLevel = ConfidenceLevel.LOW
    evidence: list[Evidence] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)


@dataclass
class ProjectModel:
    root: Path
    python_requirement: Detection[str]
    resolved_python_version: Detection[str]
    package_manager: Detection[PackageManager]
    framework: Detection[Framework]
    entry_point: Detection[ list[str] ]
    runtime_dependencies: list[str] = field(default_factory=list)
    system_dependencies: list[str] = field(default_factory=list)
    ports: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
~~~~

Note: For Python 3.10 compatibility, standard `typing.Generic` and `TypeVar` should be used in implementation rather than PEP 695 `Detection[T]` syntax. Public API models must remain stable once released.

---

## 8. Package Architecture

Use a `src/`-based layout:

~~~~text
dockseed/
├── pyproject.toml
├── README.md
├── LICENSE
├── CHANGELOG.md
├── CONTRIBUTING.md
├── SRS.md
├── src/
│   └── dockseed/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       ├── scanner.py
│       ├── models.py
│       ├── inference.py
│       ├── environment.py
│       ├── exceptions.py
│       ├── detectors/
│       │   ├── __init__.py
│       │   ├── python_version.py
│       │   ├── package_manager.py
│       │   ├── framework.py
│       │   ├── entrypoint.py
│       │   └── native_deps.py
│       ├── generators/
│       │   ├── __init__.py
│       │   ├── dockerfile.py
│       │   └── dockerignore.py
│       ├── validators/
│       │   ├── __init__.py
│       │   └── dockerfile.py
│       └── templates/
└── tests/
    ├── fixtures/
    │   ├── basic_script/
    │   ├── fastapi_project/
    │   ├── flask_project/
    │   ├── django_project/
    │   ├── celery_worker/
    │   ├── poetry_project/
    │   ├── uv_project/
    │   ├── pdm_project/
    │   └── ambiguous_project/
    ├── test_scanner.py
    ├── test_models.py
    ├── test_detectors.py
    ├── test_generators.py
    ├── test_validators.py
    ├── test_cli.py
    └── test_safety.py
~~~~

Do not create empty modules simply to match the proposed tree. Introduce modules as the corresponding functionality is implemented.

---

## 9. Public Python API

The CLI must use the same core functions exposed to Python callers.

A planned API:

~~~~python
from pathlib import Path
from dockseed import scan_project, generate_dockerfile, generate_dockerignore

project = scan_project(Path("."))

dockerfile_result = generate_dockerfile(project, include_comments=True)
dockerignore_result = generate_dockerignore(project)

print(dockerfile_result.content)
~~~~

The intended responsibilities are:

- `scan_project(path, overrides=None)` returns a structured `ProjectModel`.
- `generate_dockerfile(project, include_comments=True)` returns generated Dockerfile content, validation status, and associated assumptions.
- `generate_dockerignore(project)` returns generated `.dockerignore` content.
- A separate file-writing function handles previews, overwrite policies, and atomic filesystem changes.

Core scanning and generation functions must never invoke `input()` or require interactive terminal input. Interactive questions and terminal formatting belong strictly in the CLI layer.

---

## 10. Dependencies and Tooling

Keep runtime dependencies minimal.

- **TOML Parsing:** Use the standard library `tomllib` on Python 3.11+, and specify `tomli; python_version < "3.11"` in `pyproject.toml` so Python 3.11–3.14 environments require zero third-party TOML dependencies.
- **Standard Library First:** Use Python's standard library (`pathlib`, `ast`, `subprocess`, `json`, `enum`, `dataclasses`, `shutil`) for filesystem traversal, static code analysis, subprocess management, and general file processing.
- **Template Rendering:** Use simple, well-tested string/block assembly in Python rather than adding a heavy template engine, unless complex logic strictly justifies it.

Recommended development tools:

- `pytest` for tests.
- `pytest-cov` for coverage.
- `ruff` for linting and formatting.
- `mypy` (strict mode) for static type checking.
- `build` for package builds.
- `twine` for distribution checks.

---

## 11. Security and Privacy

Dockseed operates on local project files and must follow a conservative security model.

Required safeguards:

1. Never import or execute project code during scanning (use `ast` for source inspection).
2. Never read, log, or print secret values from `.env` files.
3. Always exclude `.env` files (while allowing `.env.example` or `.env.template`) in generated `.dockerignore` files.
4. Never copy host virtual environments into generated images.
5. Configure generated Dockerfiles to run the application as a non-root user by default.
6. Avoid following symlinks that resolve outside the selected project root during scanning.
7. Never use `shell=True` or shell interpolation when invoking optional external commands (`docker`, `podman`, `nerdctl`).
8. Never install packages on the host as part of scanning or generation.
9. Do not overwrite existing configuration without explicit `--overwrite` authorization.
10. Do not transmit source code, telemetry, or environment contents to any external service.

Build validation (`dockseed check --build`) is strictly an opt-in operation because container builds execute instructions and download external resources.

---

## 12. Testing Strategy

Testing must focus on detection accuracy, output correctness, and safe behavior across Python 3.10–3.14.

### Unit tests

Test each detector independently using small representative manifests and AST snippets.

Cases must include:

- Missing configuration files.
- Invalid TOML or malformed `requirements.txt`.
- Conflicting Python version declarations.
- Multiple dependency manifests and lockfiles (`uv.lock` vs `poetry.lock` vs `pdm.lock`).
- Out-of-context local path dependencies (`../foo`) and SSH Git URLs.
- Multiple potential entry points and commented-out false positives in Python files.
- Web frameworks missing production WSGI/ASGI servers.
- Native dependency triggers (`psycopg2`, `mysqlclient`, etc.).
- Nested project directories.
- Existing Dockerfiles and unwritable output directories.

### Golden-file tests

For representative fixture projects, compare generated Dockerfiles (both with and without `--comments`) and `.dockerignore` files against expected golden outputs.

These tests verify determinism, layer-caching order, non-root user setup, and exec-form `CMD` formatting.

### CLI tests

Verify:

- Command arguments and override flags (`--python`, `--entrypoint`, etc.).
- JSON scan output schema stability.
- Exact exit codes (`0`, `1`, `2`, `3`, `4`).
- Non-interactive / non-TTY fail-fast behavior on unresolved ambiguities.
- Confirmation and `--dry-run` behavior.
- Overwrite protection (`--overwrite`).
- Actionable error messages.

### Integration tests

Where a container runtime (`docker` or `podman`) is available, build test images from generated fixtures and verify container startup.

Container-dependent tests should be optional locally (e.g., via a `@pytest.mark.integration` marker) and run automatically in CI.

### Safety tests

Verify that:

- `.env` secret contents never appear in scan reports, logs, or generated files.
- Existing files remain unchanged by default.
- Symlinks pointing outside the project root are ignored safely.
- Project code is never imported during scanning.
- External commands are never invoked during `scan` or `init`.

---

## 13. Development Roadmap

### Phase 0 — Repository foundation

Deliverables:

- Initialize the repository and `src/dockseed/` layout.
- Configure `pyproject.toml` (with `tomli; python_version < "3.11"`).
- Configure `pytest`, `ruff`, and `mypy`.
- Set up CI matrix across Python 3.10–3.14.
- Write initial `README.md` and `SRS.md`.

Exit criteria: The package installs in editable mode, the `dockseed` CLI entry point runs, and CI passes.

### Phase 1 — Scanner, AST detectors, and normalized model

Implement:

- Project-root discovery and safe file traversal.
- Manifest and lockfile parsing (`pip`, `Poetry`, `uv`, `PDM`, `Hatch`, `Pipenv`).
- Python requirement detection and version resolution.
- AST-based framework and entry-point detection.
- Native system dependency mapping and blocker detection (local paths / SSH URLs).
- Structured evidence, confidence enums, and human/JSON scan reports (`dockseed scan`).

Exit criteria: Representative Python projects produce accurate, deterministic scan reports without modifying files or importing project code.

### Phase 2 — Dockerfile and `.dockerignore` generator

Implement:

- Base-image selection (`python:3.x-slim`).
- Layer-cached dependency installation templates for supported package managers.
- Native `apt-get` block injection.
- Non-root user setup and standard Python `ENV` variables.
- Exec-form startup commands and inline evidence-based comments.
- `.dockerignore` generation and static validation (`dockseed check`).

Exit criteria: Supported fixtures generate valid, layer-cached, non-root Dockerfiles and `.dockerignore` files that pass static validation.

### Phase 3 — CLI workflow and ambiguity handling

Implement:

- `dockseed init` with preview, confirmation prompts, and `--dry-run`.
- Explicit override flags (`--python`, `--package-manager`, `--entrypoint`, `--port`, `--no-comments`).
- Non-interactive / TTY detection and exit code enforcement (`0`–`4`).
- Atomic file writing and `--overwrite` protection.
- Targeted interactive questions for unresolved ambiguities.

Exit criteria: Both interactive and headless CI workflows operate reliably and never silently overwrite existing files or hang in non-TTY environments.

### Phase 4 — Environment awareness

Implement:

- Active interpreter and virtual-environment detection.
- Installed-versus-declared dependency cross-checking (e.g., flagging locally installed `uvicorn` missing from `requirements.txt`).
- Portability warnings.

Exit criteria: Environment data improves diagnostic warnings without polluting the authoritative dependency model.

### Phase 5 — Build validation and integration testing

Implement:

- `dockseed check --build` with `docker`, `podman`, and `nerdctl` support.
- Integration test suite building real container images from fixture projects.
- Security and symlink regression tests.

Exit criteria: Generated configurations build and start cleanly in integration CI, and failures produce actionable diagnostics.

### Phase 6 — PyPI release

Prepare:

- Finalize package metadata, `README.md`, `LICENSE`, and `CHANGELOG.md`.
- Run `build` and `twine check`.
- Configure trusted publishing to PyPI.
- Verify installation and CLI execution from a clean environment.

Exit criteria: `pip install dockseed` and `uvx dockseed` work out of the box across Python 3.10–3.14.

### Phase 7 — Post-v1 expansion

Potential future features:

- Multi-stage build templates for size optimization and complex C-extension compilation.
- Docker Compose generation (`dockseed compose`) for databases, Redis, and Celery workers.
- Configuration files (`[tool.dockseed]` in `pyproject.toml`) for persistent project overrides.
- Additional Python frameworks and Node.js / Go detectors.

---

## 14. Definition of Done for v1

Dockseed v1 is ready when:

- A user can install and run it via `pip` or `uvx` on Python 3.10–3.14.
- `dockseed scan` accurately analyzes supported Python projects and outputs human or JSON reports.
- `dockseed init` generates a layer-cached, non-root, commented Dockerfile and a safe `.dockerignore`.
- Common dependency managers (`pip`, `Poetry`, `uv`, `PDM`, `Hatch`, `Pipenv`) and native system packages are detected correctly.
- Python versions and entry points are inferred using static analysis (`ast`) with documented evidence.
- Missing production web servers and uncontainerizable path/SSH dependencies are flagged clearly.
- Ambiguous cases are handled via targeted questions interactively, or fail cleanly with exit code `3` and override instructions in headless mode.
- Existing files are protected from accidental overwrites (exit code `4`).
- Secrets and local virtual environments are excluded from the container build context.
- Generated output is deterministic and passes both static (`dockseed check`) and integration build checks.
- Tests, strict typing (`mypy`), and linting (`ruff`) pass, and the package is published to PyPI.

---

## 15. Product Principles

Dockseed follows these principles throughout development:

1. **Inspect before generating.** Never assume every Python project has the same structure.
2. **Prefer evidence over guesses.** Record why every decision was made, explain it in comments, and report uncertainty when detection is incomplete.
3. **Keep the output readable and modern.** Generated Dockerfiles should teach good practices (layer caching, non-root execution, exec-form commands) and be easily maintainable by developers.
4. **Make safe behavior the default.** Do not overwrite files, leak secrets, run containers as root, or execute project code during scanning.
5. **Stay deterministic and CI-friendly.** Identical inputs and options must produce identical output, and non-interactive runs must never hang.
6. **Separate detection from generation.** Add new detectors without rewriting the generator.
7. **Keep v1 focused.** A reliable, high-quality Python Dockerfile generator is more valuable than a broad but unreliable containerization tool.
8. **Validate claims.** Distinguish clearly between generated, statically validated, successfully built, and runtime-tested configurations.

The long-term objective is to make containerization a straightforward, educational consequence of understanding a project, rather than a manual configuration exercise.

**End of specification.**