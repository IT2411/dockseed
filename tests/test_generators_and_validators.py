"""Phase 3 tests for Dockerfile/.dockerignore generation and static validation."""

from pathlib import Path

import pytest

from dockseed.exceptions import ValidationError
from dockseed.generators import generate_dockerfile, generate_dockerignore
from dockseed.inference import scan_project
from dockseed.models import ProjectModel
from dockseed.validators import validate_dockerfile


def test_generate_fastapi_pip_with_and_without_comments(tmp_path: Path) -> None:
    (tmp_path / ".python-version").write_text("3.12\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("fastapi\nuvicorn\npsycopg2\n", encoding="utf-8")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8"
    )

    model = scan_project(tmp_path)
    df_commented = generate_dockerfile(model, include_comments=True)
    df_no_comments = generate_dockerfile(model, include_comments=False)
    di_res = generate_dockerignore(model)

    # Determinism check
    assert df_commented.content == generate_dockerfile(model, include_comments=True).content

    assert "FROM python:3.12-slim" in df_commented.content
    assert "# Base image selected for Python 3.12" in df_commented.content
    assert "# Base image selected" not in df_no_comments.content
    assert "gcc \\\n    libpq-dev" in df_commented.content
    assert "COPY requirements.txt ./" in df_commented.content
    assert "RUN pip install --no-cache-dir -r requirements.txt" in df_commented.content
    assert "USER appuser" in df_commented.content
    assert "EXPOSE 8000" in df_commented.content
    assert (
        'CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]'
        in df_commented.content
    )

    # Validate generated output
    report = validate_dockerfile(df_commented.content, model, di_res.content)
    assert report.is_valid
    assert not report.errors
    assert not report.warnings


def test_generate_uv_poetry_pdm_pipenv_and_pep621(tmp_path: Path) -> None:
    # 1. uv project with uv.lock
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "uv-demo"\ndependencies = ["fastapi", "uvicorn"]\n',
        encoding="utf-8",
    )
    (tmp_path / "uv.lock").write_text("# uv lock\n", encoding="utf-8")
    (tmp_path / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8"
    )
    model_uv = scan_project(tmp_path)
    df_uv = generate_dockerfile(model_uv)
    assert "COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/" in df_uv.content
    assert "COPY pyproject.toml uv.lock ./" in df_uv.content
    assert "RUN uv sync --frozen --no-install-project --no-dev" in df_uv.content
    assert "RUN uv sync --frozen --no-dev" in df_uv.content
    assert validate_dockerfile(df_uv.content, model_uv).is_valid

    # 2. Poetry CLI project with poetry.lock
    (tmp_path / "uv.lock").unlink()
    (tmp_path / "main.py").unlink()
    (tmp_path / "pyproject.toml").write_text(
        '[tool.poetry]\nname = "p-cli"\n[tool.poetry.dependencies]\npython = "^3.11"\n'
        '[tool.poetry.scripts]\nmytool = "mytool:main"\n',
        encoding="utf-8",
    )
    (tmp_path / "poetry.lock").write_text("# poetry lock\n", encoding="utf-8")
    model_poetry = scan_project(tmp_path)
    df_poetry = generate_dockerfile(model_poetry)
    assert "POETRY_VIRTUALENVS_CREATE=false" in df_poetry.content
    assert (
        "RUN poetry install --no-interaction --no-ansi --no-root --only main" in df_poetry.content
    )
    assert "RUN poetry install --no-interaction --no-ansi --only main" in df_poetry.content
    assert 'CMD ["mytool"]' in df_poetry.content
    assert validate_dockerfile(df_poetry.content, model_poetry).is_valid

    # 3. PDM CLI project with pdm.lock
    (tmp_path / "poetry.lock").unlink()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "pdm-cli"\n[project.scripts]\npdmtool = "pdmtool:main"\n[tool.pdm]\n',
        encoding="utf-8",
    )
    (tmp_path / "pdm.lock").write_text("# pdm lock\n", encoding="utf-8")
    model_pdm = scan_project(tmp_path)
    df_pdm = generate_dockerfile(model_pdm)
    assert "RUN pdm install --check --prod --no-editable --no-self" in df_pdm.content
    assert "RUN pdm install --check --prod --no-editable" in df_pdm.content
    assert validate_dockerfile(df_pdm.content, model_pdm).is_valid

    # 4. Pipenv project with Pipfile.lock
    (tmp_path / "pdm.lock").unlink()
    (tmp_path / "pyproject.toml").unlink()
    (tmp_path / "Pipfile").write_text('[packages]\nflask = "*"\ngunicorn = "*"\n', encoding="utf-8")
    (tmp_path / "Pipfile.lock").write_text("{}\n", encoding="utf-8")
    (tmp_path / "app.py").write_text(
        "from flask import Flask\napp = Flask(__name__)\n", encoding="utf-8"
    )
    model_pipenv = scan_project(tmp_path)
    df_pipenv = generate_dockerfile(model_pipenv)
    assert "COPY Pipfile Pipfile.lock ./" in df_pipenv.content
    assert "RUN pipenv install --system --deploy" in df_pipenv.content
    assert validate_dockerfile(df_pipenv.content, model_pipenv).is_valid

    # 5. Standard PEP 621 project with README.md
    (tmp_path / "Pipfile").unlink()
    (tmp_path / "Pipfile.lock").unlink()
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "pep621"\ndependencies = ["flask", "gunicorn"]\n',
        encoding="utf-8",
    )
    model_pep = scan_project(tmp_path)
    df_pep = generate_dockerfile(model_pep)
    assert "COPY pyproject.toml README.md ./" in df_pep.content
    assert "RUN pip install --no-cache-dir ." in df_pep.content
    assert validate_dockerfile(df_pep.content, model_pep).is_valid


def test_generate_django_and_nested_requirements(tmp_path: Path) -> None:
    (tmp_path / "manage.py").write_text("import django\n", encoding="utf-8")
    (tmp_path / "requirements").mkdir()
    (tmp_path / "requirements" / "prod.txt").write_text("django\ngunicorn\n", encoding="utf-8")
    (tmp_path / "mysite").mkdir()
    (tmp_path / "mysite" / "wsgi.py").write_text("application = None\n", encoding="utf-8")

    model = scan_project(tmp_path)
    df = generate_dockerfile(model, include_comments=True)
    assert "COPY requirements/ ./requirements/" in df.content
    assert "RUN pip install --no-cache-dir -r requirements/prod.txt" in df.content
    assert "# RUN python manage.py collectstatic --noinput" in df.content


def test_generate_missing_entrypoint_raises(tmp_path: Path) -> None:
    model = ProjectModel(root=tmp_path)
    with pytest.raises(ValidationError, match="without a resolved entry point"):
        generate_dockerfile(model)


def test_validator_catches_errors_and_warnings(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    model = ProjectModel(root=tmp_path)
    model.resolved_python_version.value = "3.12"

    bad_dockerfile = (
        "FROM python:3.10-slim\n" "COPY missing_file.txt ./\n" "USER root\n" "CMD python main.py\n"
    )
    bad_dockerignore = "README.md\n"

    report = validate_dockerfile(bad_dockerfile, model, bad_dockerignore)
    assert not report.is_valid
    assert any("missing_file.txt" in e for e in report.errors)
    assert any(".env" in e for e in report.errors)
    assert any("README.md" in e for e in report.errors)
    assert any("differs from resolved" in w for w in report.warnings)
    assert any("WORKDIR" in w for w in report.warnings)
    assert any("shell form" in w for w in report.warnings)
    assert any("non-root USER" in w for w in report.warnings)
    assert any(".venv/" in w for w in report.warnings)

    # Also test completely empty Dockerfile and broken JSON CMD
    empty_report = validate_dockerfile("CMD [invalid json]", model)
    assert not empty_report.is_valid
    assert any("missing a required FROM" in e for e in empty_report.errors)
    assert any("invalid JSON array" in e for e in empty_report.errors)
