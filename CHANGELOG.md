# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-10-18

### Added
- Initial release of `dockseed` supporting Python 3.10–3.14.
- Deterministic project scanner (`dockseed scan`) with human-readable and JSON reporting.
- Python version constraint parser and resolver across `pyproject.toml`, `.python-version`, `.tool-versions`, `runtime.txt`, and `Pipfile`.
- Package manager detection and layer-cached installation templates for `pip`, `uv`, `Poetry`, `PDM`, `Hatch`, and `Pipenv`.
- AST-based framework and entrypoint detection for `FastAPI`, `Flask`, `Django`, `Streamlit`, `Gradio`, `Celery`, CLI console scripts, and standalone scripts.
- Native Debian `-slim` `apt-get` heuristics for common C-extension packages (`psycopg2`, `mysqlclient`, `opencv-python`, etc.).
- Local virtual-environment dependency mismatch diagnostics.
- `dockseed init` generator with non-root `appuser`, exec-form `CMD`, inline evidence comments, `--dry-run`, `--yes`, `--overwrite`, and atomic file writes.
- `dockseed check` static validator and opt-in `--build` validator supporting `docker`, `podman`, and `nerdctl`.
