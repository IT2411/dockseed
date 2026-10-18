# Dockseed

**Dockseed** inspects existing Python projects and generates deterministic, best-practice `Dockerfile` and `.dockerignore` configurations automatically.

## Features

- **Evidence-Based Detection:** Infers Python version constraints, package managers (`pip`, `uv`, `Poetry`, `PDM`, `Hatch`, `Pipenv`), frameworks, and native `apt` dependencies.
- **Safe Static Inspection:** Uses Python's `ast` module to discover entry points without importing or executing project code.
- **Modern Docker Defaults:** Generates layer-cached, non-root (`appuser`), exec-form `Dockerfile` configurations with explanatory comments.
- **CI/CD Ready:** Deterministic output with strict exit codes and non-interactive override flags.

## Quickstart

~~~bash
pip install dockseed

cd my-python-project
dockseed scan
dockseed init
~~~

## Exit Codes

- `0`: Success
- `1`: General / unhandled runtime error
- `2`: Validation failed or unsupported project
- `3`: Unresolved critical ambiguity in non-interactive mode
- `4`: File overwrite blocked (use `--overwrite` to authorize)
