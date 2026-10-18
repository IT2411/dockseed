"""Phase 2 tests for AST framework detection, entrypoint inference, and code execution safety."""

import json
import sys
from pathlib import Path

import pytest

from dockseed.cli import main
from dockseed.exceptions import ExitCode
from dockseed.inference import scan_project
from dockseed.models import CLIOverrides, ConfidenceLevel, Framework


def test_safety_never_imports_or_executes_project_code(tmp_path: Path) -> None:
    """Ensure scanning a file with top-level side effects never executes them."""
    (tmp_path / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")
    (tmp_path / "evil_app.py").write_text(
        "import sys\n"
        'raise RuntimeError("DOCKSEED EXECUTED USER CODE!")\n'
        '"""\n'
        "app = Flask(__name__)\n"
        '"""\n'
        "from fastapi import FastAPI\n"
        "app: FastAPI = FastAPI()\n",
        encoding="utf-8",
    )

    model = scan_project(tmp_path)
    assert "evil_app" not in sys.modules
    # Docstring Flask should be ignored; real FastAPI annotated assignment detected
    assert model.framework.value == Framework.FASTAPI
    assert model.entry_point.value == [
        "uvicorn",
        "evil_app:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
    ]
    assert model.ports == [8000]


def test_fastapi_variants_and_missing_server(tmp_path: Path) -> None:
    # 1. FastAPI without uvicorn declared -> warns and assumes uvicorn
    (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (tmp_path / "src" / "myapi").mkdir(parents=True)
    (tmp_path / "src" / "myapi" / "__init__.py").write_text(
        "import fastapi\napi = fastapi.FastAPI()\n", encoding="utf-8"
    )
    model_no_uv = scan_project(tmp_path)
    assert model_no_uv.framework.value == Framework.FASTAPI
    assert model_no_uv.entry_point.value == [
        "uvicorn",
        "myapi:api",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
    ]
    assert any("uvicorn" in w for w in model_no_uv.warnings)

    # 2. FastAPI with granian and factory function
    (tmp_path / "requirements.txt").write_text("fastapi\ngranian\n", encoding="utf-8")
    (tmp_path / "src" / "myapi" / "__init__.py").write_text(
        "from fastapi import FastAPI\ndef create_app():\n    return FastAPI()\n",
        encoding="utf-8",
    )
    model_factory = scan_project(tmp_path)
    assert model_factory.entry_point.value == [
        "uvicorn",
        "myapi:create_app",
        "--factory",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
    ]

    # 3. FastAPI with granian direct instance and gunicorn fallback
    (tmp_path / "src" / "myapi" / "__init__.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8"
    )
    model_granian = scan_project(tmp_path)
    assert model_granian.entry_point.value == [
        "granian",
        "--interface",
        "asgi",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
        "myapi:app",
    ]

    (tmp_path / "requirements.txt").write_text("fastapi\ngunicorn\n", encoding="utf-8")
    model_gunicorn = scan_project(tmp_path)
    assert model_gunicorn.entry_point.value == [
        "gunicorn",
        "-k",
        "uvicorn.workers.UvicornWorker",
        "--bind",
        "0.0.0.0:8000",
        "myapi:app",
    ]


def test_flask_with_and_without_gunicorn(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("flask\n", encoding="utf-8")
    (tmp_path / "app.py").write_text(
        "from flask import Flask\napp = Flask(__name__)\n", encoding="utf-8"
    )

    # Without gunicorn -> warns and falls back to python -m flask run
    model = scan_project(tmp_path)
    assert model.framework.value == Framework.FLASK
    assert model.ports == [5000]
    assert model.entry_point.value == [
        "python",
        "-m",
        "flask",
        "--app",
        "app:app",
        "run",
        "--host=0.0.0.0",
        "--port=5000",
    ]
    assert any("gunicorn" in w for w in model.warnings)

    # With gunicorn and factory function
    (tmp_path / "requirements.txt").write_text("flask\ngunicorn\n", encoding="utf-8")
    (tmp_path / "app.py").write_text(
        "import flask\ndef create_app():\n    return flask.Flask(__name__)\n",
        encoding="utf-8",
    )
    model_gun = scan_project(tmp_path)
    assert model_gun.entry_point.value == [
        "gunicorn",
        "--bind",
        "0.0.0.0:5000",
        "app:create_app()",
    ]


def test_django_wsgi_asgi_and_runserver(tmp_path: Path) -> None:
    (tmp_path / "manage.py").write_text("#!/usr/bin/env python\nimport django\n", encoding="utf-8")
    (tmp_path / "myproj").mkdir()
    (tmp_path / "myproj" / "settings.py").write_text(
        'WSGI_APPLICATION = "myproj.wsgi.application"\n', encoding="utf-8"
    )
    (tmp_path / "myproj" / "wsgi.py").write_text("application = None\n", encoding="utf-8")
    (tmp_path / "myproj" / "asgi.py").write_text("application = None\n", encoding="utf-8")

    # 1. With gunicorn
    (tmp_path / "requirements.txt").write_text("django\ngunicorn\n", encoding="utf-8")
    model_wsgi = scan_project(tmp_path)
    assert model_wsgi.framework.value == Framework.DJANGO
    assert model_wsgi.entry_point.value == [
        "gunicorn",
        "--bind",
        "0.0.0.0:8000",
        "myproj.wsgi:application",
    ]

    # 2. With daphne (ASGI)
    (tmp_path / "requirements.txt").write_text("django\ndaphne\n", encoding="utf-8")
    model_asgi = scan_project(tmp_path)
    assert model_asgi.entry_point.value == [
        "daphne",
        "-b",
        "0.0.0.0",
        "-p",
        "8000",
        "myproj.asgi:application",
    ]

    # 3. Without production server -> runserver fallback
    (tmp_path / "requirements.txt").write_text("django\n", encoding="utf-8")
    model_dev = scan_project(tmp_path)
    assert model_dev.entry_point.value == [
        "python",
        "manage.py",
        "runserver",
        "0.0.0.0:8000",
    ]


def test_streamlit_gradio_celery_and_ambiguity(tmp_path: Path) -> None:
    # Streamlit
    (tmp_path / "requirements.txt").write_text("streamlit\n", encoding="utf-8")
    (tmp_path / "dashboard.py").write_text(
        "import streamlit as st\nst.title('Hello')\n", encoding="utf-8"
    )
    model_st = scan_project(tmp_path)
    assert model_st.framework.value == Framework.STREAMLIT
    assert model_st.ports == [8501]
    assert model_st.entry_point.value == [
        "streamlit",
        "run",
        "dashboard.py",
        "--server.port=8501",
        "--server.address=0.0.0.0",
    ]

    # Gradio
    (tmp_path / "dashboard.py").unlink()
    (tmp_path / "requirements.txt").write_text("gradio\n", encoding="utf-8")
    (tmp_path / "ui.py").write_text(
        "import gradio as gr\n"
        "demo = gr.Interface(fn=None, inputs='text', outputs='text')\n"
        "demo.launch()\n",
        encoding="utf-8",
    )
    model_gr = scan_project(tmp_path)
    assert model_gr.framework.value == Framework.GRADIO
    assert model_gr.ports == [7860]
    assert model_gr.entry_point.value == ["python", "ui.py"]

    # Ambiguous project: Both FastAPI and Celery worker
    (tmp_path / "ui.py").unlink()
    (tmp_path / "requirements.txt").write_text("fastapi\nuvicorn\ncelery\n", encoding="utf-8")
    (tmp_path / "api.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8"
    )
    (tmp_path / "tasks.py").write_text(
        "from celery import Celery\nworker = Celery('tasks')\n", encoding="utf-8"
    )
    model_amb = scan_project(tmp_path)
    assert len(model_amb.entry_point.candidates) == 2
    assert model_amb.entry_point.confidence == ConfidenceLevel.LOW
    assert len(model_amb.entry_point.conflicts) == 1


def test_cli_scripts_standalone_and_overrides(tmp_path: Path) -> None:
    # 1. PEP 621 console script + Typer AST detection
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "mycli"\n[project.scripts]\nmycli = "mycli.main:app"\n',
        encoding="utf-8",
    )
    (tmp_path / "mycli").mkdir()
    (tmp_path / "mycli" / "main.py").write_text(
        "import typer\napp = typer.Typer()\n", encoding="utf-8"
    )
    model_cli = scan_project(tmp_path)
    assert model_cli.framework.value == Framework.CLI
    assert model_cli.entry_point.value == ["mycli"]

    # 2. Standalone __main__ block + broken syntax file skipped gracefully
    (tmp_path / "pyproject.toml").unlink()
    (tmp_path / "mycli" / "main.py").unlink()
    (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    (tmp_path / "script.py").write_text(
        'if "__main__" == __name__:\n    print("running")\n', encoding="utf-8"
    )
    model_script = scan_project(tmp_path)
    assert model_script.framework.value == Framework.SCRIPT
    assert model_script.entry_point.value == ["python", "script.py"]
    assert any("syntax error" in w for w in model_script.warnings)

    # 3. Conventional main.py without __main__ guard
    (tmp_path / "script.py").unlink()
    (tmp_path / "main.py").write_text("print('hello world')\n", encoding="utf-8")
    model_conv = scan_project(tmp_path)
    assert model_conv.framework.value == Framework.SCRIPT
    assert model_conv.entry_point.value == ["python", "main.py"]

    # 4. CLI overrides for entrypoint and port
    model_ovr = scan_project(tmp_path, CLIOverrides(entrypoint="mycli.main:app", port=9000))
    assert model_ovr.ports == [9000]
    assert model_ovr.entry_point.value == [
        "uvicorn",
        "mycli.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        "9000",
    ]


def test_cli_scan_text_and_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "requirements.txt").write_text(
        "-e ../outside_lib\npsycopg2\nfastapi\nuvicorn\n", encoding="utf-8"
    )
    (tmp_path / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8"
    )

    code_text = main(["scan", str(tmp_path)])
    assert code_text == int(ExitCode.SUCCESS)
    out_text = capsys.readouterr().out
    assert "Framework: fastapi" in out_text
    assert "System packages: gcc, libpq-dev" in out_text
    assert "Blockers:" in out_text

    code_json = main(["scan", str(tmp_path), "--format", "json"])
    assert code_json == int(ExitCode.SUCCESS)
    out_json = capsys.readouterr().out
    parsed = json.loads(out_json)
    assert parsed["framework"]["value"] == "fastapi"
    assert parsed["ports"] == [8000]
