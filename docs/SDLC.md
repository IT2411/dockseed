# Dockseed — Software Development Life Cycle (SDLC) & Phase Execution Plan

**Document Version:** 1.0.0  
**Target Release:** `dockseed` v0.1.0  
**Supported Python Matrix:** Python 3.10, 3.11, 3.12, 3.13, 3.14  

---

## 1. SDLC Methodology & Engineering Standards

Dockseed follows an **Iterative, Test-Driven, Gate-Controlled SDLC**. Because Dockseed is a deterministic developer tool that inspects codebases and generates infrastructure configuration, no phase may advance to the next until all functional deliverables, static quality gates, and security invariants for the current phase are 100% satisfied.

### 1.1 Development Loop (Per Feature / Module)

Every component must follow this inner development loop:

1. **Specification & Interface Design:** Define strict data structures (`dataclass` / `Enum`) and function signatures with full type annotations in `models.py` or module interfaces.
2. **Fixture & Test Creation (TDD):** Create minimal, isolated test fixtures (manifests, mock AST trees, directory structures) representing happy paths, edge cases, and failure modes.
3. **Implementation:** Write the minimal, standard-library-first code to satisfy the tests without introducing side effects.
4. **Quality & Safety Verification:** Run linting, strict type checking, unit tests, and safety assertions locally.
5. **CI Verification & Merge:** Validate across the full Python 3.10–3.14 matrix in Continuous Integration.

### 1.2 Global Quality Gates (Enforced on Every Commit/PR)

Every phase is subject to the following automated checks:

~~~~bash
# 1. Formatting & Linting
ruff check src/ tests/
ruff format --check src/ tests/

# 2. Strict Static Type Checking
mypy --strict src/ tests/

# 3. Unit & Golden-File Test Suite with Coverage
pytest -m "not integration" --cov=dockseed --cov-report=term-missing --cov-fail-under=90
~~~~

---

## 2. Phase-by-Phase Execution Plan

### Phase 0: Repository Foundation & CI/CD Pipeline

**Objective:** Establish a reproducible development environment, packaging metadata, core data models, and automated quality gates before writing business logic.

#### Deliverables
- `pyproject.toml` configured with PEP 621 metadata, `src/` layout, entry points (`dockseed = "dockseed.cli:main"`), and conditional dependency (`tomli>=2.0.0; python_version < "3.11"`).
- Core domain models (`src/dockseed/models.py`) implementing `ConfidenceLevel`, `PackageManager`, `Framework`, `Evidence`, `Detection[T]`, `ProjectModel`, and `CLI Overrides`.
- Custom exception hierarchy (`src/dockseed/exceptions.py`) mapped to CLI exit codes (`0` through `4`).
- Minimal CLI skeleton (`src/dockseed/cli.py`, `src/dockseed/__main__.py`) using `argparse` supporting `--version` and subcommands (`scan`, `init`, `check`).
- GitHub Actions (or equivalent CI) workflow executing across Python 3.10–3.14.

#### Tests Required
- `tests/test_models.py`: Verify immutability of `Evidence`, serialization of `ProjectModel` to dictionary/JSON, and deterministic sorting of evidence lists.
- `tests/test_cli_skeleton.py`: Verify `dockseed --version` and `python -m dockseed --help` return exit code `0`.

#### Quality Checks & Exit Criteria
- [ ] Editable install (`pip install -e ".[dev]"`) succeeds on all supported Python versions.
- [ ] `ruff check`, `ruff format --check`, and `mypy --strict` pass with 0 warnings/errors.
- [ ] `python -m build` produces valid wheel (`.whl`) and source distribution (`.tar.gz`).

---

### Phase 1: Project Discovery, Manifest Parsing & Core Detectors

**Objective:** Safely traverse a target directory, parse project configuration files, and deterministically detect Python version requirements, package managers, native system dependencies, and containerization blockers.

#### Deliverables
- `src/dockseed/scanner.py`: Safe filesystem walker that ignores excluded directories (`.git`, `.venv`, `venv`, `__pycache__`, `node_modules`, `build`, `dist`), sorts all file paths deterministically, and refuses to follow symlinks resolving outside the project root.
- `src/dockseed/detectors/python_version.py`: Evaluates CLI overrides, `requires-python`, `tool.poetry.dependencies.python`, `Pipfile`, `.python-version`, `.tool-versions`, and `runtime.txt`. Resolves version ranges (e.g., `>=3.11,<3.14` -> `3.13` or `3.12` per documented rule) and records `Evidence`.
- `src/dockseed/detectors/package_manager.py`: Parses `pyproject.toml`, `requirements*.txt`, `Pipfile`, and inspects lockfiles (`uv.lock`, `poetry.lock`, `pdm.lock`, `Pipfile.lock`) to determine the authoritative `PackageManager` and extract runtime dependencies.
- `src/dockseed/detectors/native_deps.py`: Maps declared Python dependencies (e.g., `psycopg2`, `mysqlclient`, `opencv-python`, `git+https`) to Debian `-slim` `apt-get` packages, and flags blockers (`../local/path`, `git+ssh://`).

#### Tests Required
- `tests/test_scanner.py`:
  - Verify deterministic file ordering regardless of OS filesystem return order.
  - Verify external symlinks are ignored and logged as warnings.
  - Verify `.env` files are detected by presence only (contents never read).
- `tests/test_detectors_python.py`:
  - Test exact pins, PEP 440 version specifiers, Poetry caret/tilde constraints, conflicting declarations, and fallback to active interpreter (`ConfidenceLevel.LOW`).
- `tests/test_detectors_pkg_manager.py`:
  - Test single-manager projects (`pip`, `uv`, `poetry`, `pdm`, `hatch`, `pipenv`).
  - Test multi-manifest conflict resolution (e.g., `requirements.txt` + `poetry.lock` prioritizes `poetry` with conflict warning).
  - Test malformed `pyproject.toml` and invalid `requirements.txt` lines.
  - Test detection of containerization blockers (`-e ../shared`, `git+ssh://git@github.com/...`).
- `tests/test_detectors_native.py`:
  - Verify `psycopg2` triggers `libpq-dev` + `gcc` and emits a `psycopg2-binary` suggestion.
  - Verify `psycopg2-binary` does *not* trigger `gcc`.

#### Quality Checks & Exit Criteria
- [ ] Zero network calls or subprocess invocations during scanning.
- [ ] 95%+ branch coverage across `scanner.py`, `python_version.py`, `package_manager.py`, and `native_deps.py`.
- [ ] Malformed user TOML/text files raise clean, actionable `DockseedScanError` exceptions rather than uncaught tracebacks.

---

### Phase 2: AST Static Analysis — Framework & Entry-Point Inference

**Objective:** Identify the application's framework, workload type, exposed ports, and startup command using Python's `ast` module without importing or executing user code.

#### Deliverables
- `src/dockseed/detectors/framework.py`: Cross-references declared dependencies with AST imports and object instantiations to detect `FastAPI`, `Flask`, `Django`, `Streamlit`, `Gradio`, `Celery`, `CLI` (`click`/`typer`/`argparse`), or standalone `Script`.
- `src/dockseed/detectors/entrypoint.py`:
  - Inspects `[project.scripts]` and `[tool.poetry.scripts]`.
  - Uses `ast.NodeVisitor` to locate `FastAPI()`, `Flask()`, `Celery()`, and `if __name__ == "__main__":` blocks.
  - Verifies whether production WSGI/ASGI runners (`uvicorn`, `gunicorn`, `granian`, `daphne`) are present in `runtime_dependencies`.
  - Detects Django `manage.py`, `WSGI_APPLICATION`, and `STATIC_ROOT` settings.
  - Infers default framework ports (e.g., `8000` for FastAPI/Django, `5000` for Flask, `8501` for Streamlit, `7860` for Gradio, none for Celery/CLI).
- `src/dockseed/inference.py`: Orchestrates Phase 1 and Phase 2 detectors into a unified `ProjectModel` and implements `dockseed scan` (human and `--format json` outputs).

#### Tests Required
- `tests/test_detectors_ast.py`:
  - Verify AST visitor ignores `app = FastAPI()` inside multiline docstrings or comments.
  - Verify detection of factory pattern functions (e.g., `def create_app() -> FastAPI:`).
  - Verify handling of syntax errors in user `.py` files (gracefully skip file and add warning).
- `tests/test_detectors_entrypoint.py`:
  - Verify `FastAPI` + `uvicorn` produces `["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]` with `ConfidenceLevel.HIGH`.
  - Verify `Flask` *without* `gunicorn` emits a missing production server warning and falls back safely.
  - Verify project with both `app/main.py` (FastAPI) and `app/worker.py` (Celery) records multiple candidates for ambiguity resolution.
- `tests/test_safety_no_import.py`:
  - Place a fixture `.py` file containing `raise RuntimeError("CODE EXECUTED")` at the top level; verify `scan_project()` succeeds without triggering the exception.

#### Quality Checks & Exit Criteria
- [ ] `dockseed scan --format json` outputs strictly valid, deterministic JSON matching the documented schema across all fixture projects.
- [ ] AST parsing completes in < 200ms for a 100-file Python repository.
- [ ] Zero user modules imported into `sys.modules` during `scan_project()`.

---

### Phase 3: Dockerfile & `.dockerignore` Generation + Static Validation

**Objective:** Transform a resolved `ProjectModel` into a readable, layer-cached, non-root `Dockerfile` and conservative `.dockerignore`, and validate the output statically.

#### Deliverables
- `src/dockseed/generators/dockerfile.py`:
  - Base image formatter (`python:<resolved_version>-slim`).
  - Standard environment block (`PYTHONDONTWRITEBYTECODE=1`, `PYTHONUNBUFFERED=1`, tool-specific cache disabling).
  - Conditional `apt-get` layer for `system_dependencies` with `--no-install-recommends` and apt list cleanup.
  - Layer-cached dependency installation per `PackageManager`:
    - `pip` (`requirements.txt` vs `pyproject.toml`).
    - `uv` (`COPY pyproject.toml uv.lock ./` -> `uv sync --frozen --no-install-project --no-dev`).
    - `poetry` (`COPY pyproject.toml poetry.lock ./` -> `poetry install --no-root --only main`).
    - `pdm` / `pipenv` / `hatch` equivalents.
  - Non-root user creation (`useradd --create-home --shell /bin/bash appuser`) and ownership handoff (`COPY --chown=appuser:appuser . .` + `USER appuser`).
  - Django `collectstatic` handling when applicable.
  - `EXPOSE <port>` and JSON array exec-form `CMD [...]`.
  - Evidence-based inline comment injector (`include_comments=True/False`).
- `src/dockseed/generators/dockerignore.py`: Generates exclusions for `.git`, `.venv`, `__pycache__`, caches, build artifacts, and `.env*` (preserving `.env.example` and files required by `pyproject.toml` such as `README.md`).
- `src/dockseed/validators/dockerfile.py`: Static analyzer verifying instruction order, base image alignment, `COPY` source existence, non-root `USER` presence, exec-form `CMD`, and `.dockerignore` safety.

#### Tests Required
- `tests/test_generators_golden.py`:
  - Golden-file comparison tests for all fixture projects (`basic_script`, `fastapi_project`, `flask_project`, `django_project`, `celery_worker`, `poetry_project`, `uv_project`, `pdm_project`) both with and without comments.
- `tests/test_dockerignore.py`:
  - Verify `.env` and `.venv/` are always ignored.
  - Verify `README.md` is *not* ignored if `pyproject.toml` specifies `readme = "README.md"`.
- `tests/test_validators.py`:
  - Verify validator catches missing `FROM`, shell-form `CMD`, root execution warnings, and `COPY` instructions referencing non-existent files.

#### Quality Checks & Exit Criteria
- [ ] All generated fixture Dockerfiles pass internal static validation (`validators/dockerfile.py`) with 0 errors.
- [ ] External linter check (e.g., `hadolint` if available in CI) passes on all golden Dockerfile fixtures without high/medium severity warnings.
- [ ] Repeated calls to `generate_dockerfile()` produce byte-for-byte identical strings.

---

### Phase 4: CLI Workflow, Ambiguity Resolution & Safe File Operations

**Objective:** Connect scanning, ambiguity resolution, validation, and atomic file writing into the interactive and headless CLI commands (`dockseed init`, `dockseed check`).

#### Deliverables
- `src/dockseed/cli.py`:
  - Full implementation of `dockseed init` and `dockseed check`.
  - Override flags (`--python`, `--package-manager`, `--entrypoint`, `--port`, `--no-comments`, `--dry-run`, `--yes`, `--overwrite`).
  - Interactive ambiguity prompt engine (only triggered when `sys.stdin.isatty()` is `True` and `--yes` is `False`).
  - Fail-fast headless ambiguity handler: exits with code `3` and prints exact CLI flags needed to resolve the ambiguity when `--yes` is used or `isatty()` is `False`.
- Safe File Writer utility:
  - Previews planned file creations/overwrites.
  - Enforces `--overwrite` protection (exits with code `4` if target files exist and `--overwrite` is not set).
  - Writes files atomically via temporary file + `os.replace()`.

#### Tests Required
- `tests/test_cli_init.py`:
  - Test `--dry-run` prints output and writes zero files to disk.
  - Test existing `Dockerfile` blocks execution with exit code `4` unless `--overwrite` is passed.
  - Test `ambiguous_project` fixture in non-TTY / `--yes` mode exits with code `3` and outputs required override flags.
  - Test `ambiguous_project` fixture with explicit override flags (`--entrypoint ...`) succeeds with exit code `0`.
  - Test interactive TTY prompt simulation (via `monkeypatch` on `sys.stdin`).
- `tests/test_atomic_write.py`:
  - Simulate write failure / permission error (`chmod 500` directory) and verify exit code `1` with no partial/corrupted files left behind.

#### Quality Checks & Exit Criteria
- [ ] All 5 exit codes (`0`, `1`, `2`, `3`, `4`) are explicitly tested and verified.
- [ ] CLI never hangs on `input()` when invoked with `stdin=subprocess.DEVNULL`.
- [ ] Public Python API (`scan_project`, `generate_dockerfile`, `generate_dockerignore`) verified to have zero dependencies on CLI/TTY modules.

---

### Phase 5: Environment Inspection & Diagnostics

**Objective:** Enrich `dockseed scan` and `dockseed init` with optional active virtual-environment inspection to catch undeclared dependencies before container builds fail.

#### Deliverables
- `src/dockseed/environment.py`:
  - Detects active Python interpreter version, `sys.prefix`, `VIRTUAL_ENV`, or `CONDA_PREFIX`.
  - Uses `importlib.metadata` (or safe subprocess `python -m pip list --format=json` on target `.venv` interpreter) to inspect installed packages without importing them.
  - Computes set difference between declared `runtime_dependencies` and environment-installed packages (highlighting critical missing runners like `uvicorn`/`gunicorn` or framework packages).

#### Tests Required
- `tests/test_environment.py`:
  - Mock `importlib.metadata.distributions()` containing `uvicorn` while `requirements.txt` only lists `fastapi`; verify a high-visibility diagnostic warning is added to `ProjectModel.warnings`.
  - Verify that incidental dev tools installed in the environment (`pytest`, `ruff`, `ipython`) are never added to `ProjectModel.runtime_dependencies`.

#### Quality Checks & Exit Criteria
- [ ] Environment inspection never alters the deterministic `Dockerfile` output unless a missing runner fallback is triggered, and always prioritizes manifest/lockfile declarations.
- [ ] Works cleanly when no virtual environment is active.

---

### Phase 6: Container Build Validation & End-to-End Integration Testing

**Objective:** Validate that the Dockerfiles generated by Dockseed actually build and run inside real container engines (`docker`, `podman`, `nerdctl`).

#### Deliverables
- `dockseed check --build [--runtime <docker|podman|nerdctl>]`:
  - Auto-detects container CLI on `PATH` if `--runtime` is omitted.
  - Executes `subprocess.run([runtime, "build", ...], shell=False)` safely using a temporary image tag and cleans up the image afterward.
  - Formats build errors into actionable diagnostics.
- End-to-End CI Integration Suite (`tests/test_integration_builds.py`).

#### Tests Required
- `tests/test_check_build_unit.py`:
  - Verify `shell=False` is strictly enforced in subprocess calls.
  - Verify actionable error message and exit code `2` when no container runtime (`docker`/`podman`/`nerdctl`) is installed on `PATH`.
- `tests/test_integration_builds.py` (Marked `@pytest.mark.integration`):
  - Run `dockseed init --yes` on every fixture project (`basic_script`, `fastapi_project`, `flask_project`, `django_project`, `poetry_project`, `uv_project`).
  - Build each generated image using Docker/Podman.
  - Run the container, verify it executes as non-root (`whoami` == `appuser`), and for web fixtures, verify HTTP response on the exposed port.

#### Quality Checks & Exit Criteria
- [ ] 100% of fixture projects build into working container images in CI.
- [ ] Rebuilding a fixture image after modifying only a `.py` source file utilizes the cached dependency layer (verified via build log inspection).
- [ ] All integration containers run as `appuser` (UID != 0) and terminate cleanly (< 2 seconds) on `docker stop` (`SIGTERM`).

---

### Phase 7: Pre-Release Hardening, Documentation & PyPI Distribution

**Objective:** Finalize documentation, verify packaging integrity, conduct security regression audits, and publish `dockseed` v0.1.0 to PyPI.

#### Deliverables
- Comprehensive `README.md` with quickstart, CLI reference, exit code table, Python API usage, and supported frameworks/package managers.
- `CHANGELOG.md`, `CONTRIBUTING.md`, and `LICENSE`.
- GitHub Actions release workflow using PyPI Trusted Publishing (OIDC).

#### Pre-Release Quality & Security Audit Checklist
- [ ] **Matrix Verification:** Full unit + integration test suite passes on Python 3.10, 3.11, 3.12, 3.13, and 3.14.
- [ ] **Security Audit:**
  - [ ] Confirm zero occurrences of `eval()`, `exec()`, `importlib.import_module()` on user paths, or `subprocess.run(..., shell=True)` in `src/dockseed/`.
  - [ ] Confirm `.env` file contents are never read in `src/dockseed/`.
  - [ ] Confirm path traversal / external symlink tests pass on Linux, macOS, and Windows.
- [ ] **Artifact Verification:**
  ~~~~bash
  python -m build
  twine check --strict dist/*
  ~~~~
- [ ] **Clean-Room Installation Smoke Test:**
  Install the built wheel into an isolated environment (`uvx --from ./dist/dockseed-0.1.0-py3-none-any.whl dockseed --version` and `pip install dist/*.whl`) outside the repository root and run `dockseed scan` and `dockseed init --dry-run` against a sample project.

---

## 3. Summary Matrix of Phase Quality Gates

| Phase | Core Focus | Primary Test Suite | Required Coverage | Blocking Quality Gate |
| :--- | :--- | :--- | :--- | :--- |
| **Phase 0** | Foundation & Models | `test_models.py`, `test_cli_skeleton.py` | 100% (models) | `mypy --strict`, `ruff`, `build` |
| **Phase 1** | Scanner & Manifests | `test_scanner.py`, `test_detectors_*.py` | >= 95% | Symlink safety, deterministic sorting |
| **Phase 2** | AST & Entry Points | `test_detectors_ast.py`, `test_safety_no_import.py` | >= 90% | Zero user code execution, valid JSON output |
| **Phase 3** | Generators & Validators | `test_generators_golden.py`, `test_validators.py` | >= 95% | Golden file match, static validation pass |
| **Phase 4** | CLI & Safe I/O | `test_cli_init.py`, `test_atomic_write.py` | >= 90% | Exit codes `0–4`, non-TTY fail-fast, atomic write |
| **Phase 5** | Environment Diagnostics | `test_environment.py` | >= 90% | Manifest precedence over `.venv` packages |
| **Phase 6** | Build & Integration | `test_integration_builds.py` | N/A (E2E) | Real `docker build` + non-root runtime check |
| **Phase 7** | Release & Packaging | Clean-room smoke tests | >= 90% (Global) | `twine check --strict`, OIDC PyPI publish |