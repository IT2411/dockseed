"""Entry-point, production server verification, and port inference for Dockseed."""

import re
import shlex
from pathlib import Path

from dockseed.detectors.framework import PythonFileASTInfo
from dockseed.models import (
    CLIOverrides,
    ConfidenceLevel,
    Framework,
    ProjectModel,
)
from dockseed.scanner import ScanContext

CONVENTIONAL_SCRIPT_NAMES: tuple[str, ...] = (
    "main.py",
    "app.py",
    "run.py",
    "server.py",
    "cli.py",
    "worker.py",
    "app/main.py",
    "src/main.py",
)

DEFAULT_FRAMEWORK_PORTS: dict[Framework, int] = {
    Framework.FASTAPI: 8000,
    Framework.DJANGO: 8000,
    Framework.FLASK: 5000,
    Framework.STREAMLIT: 8501,
    Framework.GRADIO: 7860,
}


def _find_django_wsgi_or_asgi(ctx: ScanContext) -> tuple[str | None, str | None]:
    """Search settings.py or wsgi.py/asgi.py to infer the Django application module."""
    wsgi_mod: str | None = None
    asgi_mod: str | None = None

    for rel_path in ctx.files:
        if rel_path.name == "wsgi.py":
            parts = list(rel_path.with_suffix("").parts)
            if parts and parts[0] == "src" and len(parts) > 1:
                parts = parts[1:]
            wsgi_mod = ".".join(parts) + ":application"
        elif rel_path.name == "asgi.py":
            parts = list(rel_path.with_suffix("").parts)
            if parts and parts[0] == "src" and len(parts) > 1:
                parts = parts[1:]
            asgi_mod = ".".join(parts) + ":application"
        elif rel_path.name == "settings.py":
            content = ctx.read_text_safe(rel_path.as_posix())
            if content:
                match = re.search(r'WSGI_APPLICATION\s*=\s*["\']([^"\']+)["\']', content)
                if match:
                    raw_wsgi = match.group(1).strip()
                    if "." in raw_wsgi:
                        mod_part, attr_part = raw_wsgi.rsplit(".", 1)
                        wsgi_mod = f"{mod_part}:{attr_part}"
    return wsgi_mod, asgi_mod


def _parse_override_entrypoint(raw_entrypoint: str, fw: Framework, port: int) -> list[str]:
    """Convert an override string ('app.main:app' or 'python main.py') into exec-form."""
    stripped = raw_entrypoint.strip()
    # Shorthand module:app syntax for ASGI/WSGI web frameworks
    if re.match(r"^[A-Za-z0-9_.]+\:[A-Za-z0-9_]+(\(\))?$", stripped):
        if fw == Framework.FLASK:
            return ["gunicorn", "--bind", f"0.0.0.0:{port}", stripped]
        return ["uvicorn", stripped, "--host", "0.0.0.0", "--port", str(port)]
    return shlex.split(stripped)


def detect_entrypoint(
    ctx: ScanContext,
    model: ProjectModel,
    ast_infos: list[PythonFileASTInfo],
    overrides: CLIOverrides | None = None,
) -> None:
    """Infer startup command (exec-form), verify production servers, and set ports."""
    fw = model.framework.value or Framework.UNKNOWN
    deps = set(model.runtime_dependencies)

    # 1. Resolve port first (CLI override or framework default)
    if overrides and overrides.port is not None:
        port = overrides.port
        model.ports = [port]
    elif fw in DEFAULT_FRAMEWORK_PORTS:
        port = DEFAULT_FRAMEWORK_PORTS[fw]
        model.ports = [port]
    else:
        port = 8000

    # 2. Handle explicit CLI entrypoint override
    if overrides and overrides.entrypoint:
        cmd = _parse_override_entrypoint(overrides.entrypoint, fw, port)
        model.entry_point.value = cmd
        model.entry_point.confidence = ConfidenceLevel.HIGH
        model.entry_point.add_evidence(
            source="CLI --entrypoint",
            detector="entrypoint",
            description=f"Explicit entrypoint override provided: {cmd}",
            confidence=ConfidenceLevel.HIGH,
        )
        return

    candidate_commands: list[tuple[list[str], str, str, ConfidenceLevel]] = []

    # 3. Check FastAPI candidates
    for info in ast_infos:
        for var in info.fastapi_vars:
            target = f"{info.module_path}:{var}"
            if "uvicorn" in deps:
                cmd = ["uvicorn", target, "--host", "0.0.0.0", "--port", str(port)]
                conf = ConfidenceLevel.HIGH
                desc = f"FastAPI app '{target}' with declared uvicorn server"
            elif "granian" in deps:
                cmd = [
                    "granian",
                    "--interface",
                    "asgi",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    str(port),
                    target,
                ]
                conf = ConfidenceLevel.HIGH
                desc = f"FastAPI app '{target}' with declared granian server"
            elif "gunicorn" in deps:
                cmd = [
                    "gunicorn",
                    "-k",
                    "uvicorn.workers.UvicornWorker",
                    "--bind",
                    f"0.0.0.0:{port}",
                    target,
                ]
                conf = ConfidenceLevel.MEDIUM
                desc = f"FastAPI app '{target}' with gunicorn"
            else:
                cmd = ["uvicorn", target, "--host", "0.0.0.0", "--port", str(port)]
                conf = ConfidenceLevel.MEDIUM
                desc = f"FastAPI app '{target}' (uvicorn assumed)"
                warn = (
                    "FastAPI detected, but 'uvicorn' is not listed in declared "
                    "dependencies. Add 'uvicorn' to your project dependencies."
                )
                if warn not in model.warnings:
                    model.warnings.append(warn)
            candidate_commands.append((cmd, info.rel_path, desc, conf))

        for func_name, func_fw in info.factory_funcs.items():
            if func_fw == Framework.FASTAPI:
                target = f"{info.module_path}:{func_name}"
                cmd = [
                    "uvicorn",
                    target,
                    "--factory",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    str(port),
                ]
                candidate_commands.append(
                    (
                        cmd,
                        info.rel_path,
                        f"FastAPI app factory '{target}'",
                        ConfidenceLevel.HIGH if "uvicorn" in deps else ConfidenceLevel.MEDIUM,
                    )
                )

    # 4. Check Flask candidates
    for info in ast_infos:
        for var in info.flask_vars:
            target = f"{info.module_path}:{var}"
            if "gunicorn" in deps:
                cmd = ["gunicorn", "--bind", f"0.0.0.0:{port}", target]
                conf = ConfidenceLevel.HIGH
                desc = f"Flask app '{target}' with declared gunicorn server"
            else:
                cmd = [
                    "python",
                    "-m",
                    "flask",
                    "--app",
                    target,
                    "run",
                    "--host=0.0.0.0",
                    f"--port={port}",
                ]
                conf = ConfidenceLevel.MEDIUM
                desc = f"Flask app '{target}' using built-in server (gunicorn not declared)"
                warn = (
                    "Flask detected without a production WSGI server ('gunicorn'). "
                    "Falling back to 'python -m flask run'; consider adding 'gunicorn'."
                )
                if warn not in model.warnings:
                    model.warnings.append(warn)
            candidate_commands.append((cmd, info.rel_path, desc, conf))

        for func_name, func_fw in info.factory_funcs.items():
            if func_fw == Framework.FLASK:
                target = f"{info.module_path}:{func_name}()"
                if "gunicorn" in deps:
                    cmd = ["gunicorn", "--bind", f"0.0.0.0:{port}", target]
                else:
                    cmd = [
                        "python",
                        "-m",
                        "flask",
                        "--app",
                        f"{info.module_path}:{func_name}",
                        "run",
                        "--host=0.0.0.0",
                        f"--port={port}",
                    ]
                candidate_commands.append(
                    (cmd, info.rel_path, f"Flask app factory '{target}'", ConfidenceLevel.MEDIUM)
                )

    # 5. Check Django
    if fw == Framework.DJANGO:
        wsgi_target, asgi_target = _find_django_wsgi_or_asgi(ctx)
        if "gunicorn" in deps and wsgi_target:
            candidate_commands.append(
                (
                    ["gunicorn", "--bind", f"0.0.0.0:{port}", wsgi_target],
                    "wsgi.py",
                    f"Django WSGI application '{wsgi_target}' with gunicorn",
                    ConfidenceLevel.HIGH,
                )
            )
        elif ("uvicorn" in deps or "daphne" in deps) and asgi_target:
            runner = "uvicorn" if "uvicorn" in deps else "daphne"
            cmd = (
                ["uvicorn", asgi_target, "--host", "0.0.0.0", "--port", str(port)]
                if runner == "uvicorn"
                else ["daphne", "-b", "0.0.0.0", "-p", str(port), asgi_target]
            )
            candidate_commands.append(
                (
                    cmd,
                    "asgi.py",
                    f"Django ASGI application '{asgi_target}' with {runner}",
                    ConfidenceLevel.HIGH,
                )
            )
        else:
            warn = (
                "Django detected without 'gunicorn' or 'uvicorn' in dependencies; "
                "falling back to 'manage.py runserver'."
            )
            if warn not in model.warnings:
                model.warnings.append(warn)
            candidate_commands.append(
                (
                    ["python", "manage.py", "runserver", f"0.0.0.0:{port}"],
                    "manage.py",
                    "Django development server fallback",
                    ConfidenceLevel.MEDIUM,
                )
            )

    # 6. Check Streamlit & Gradio
    if fw == Framework.STREAMLIT:
        st_files = [
            info for info in ast_infos if "streamlit" in info.imports or info.has_streamlit_calls
        ]
        for info in st_files:
            cmd = [
                "streamlit",
                "run",
                info.rel_path,
                f"--server.port={port}",
                "--server.address=0.0.0.0",
            ]
            candidate_commands.append(
                (cmd, info.rel_path, f"Streamlit script '{info.rel_path}'", ConfidenceLevel.HIGH)
            )

    if fw == Framework.GRADIO:
        gr_files = [
            info for info in ast_infos if "gradio" in info.imports or info.has_gradio_launch
        ]
        for info in gr_files:
            cmd = ["python", info.rel_path]
            candidate_commands.append(
                (cmd, info.rel_path, f"Gradio application '{info.rel_path}'", ConfidenceLevel.HIGH)
            )

    # 7. Check Celery workers
    for info in ast_infos:
        for var in info.celery_vars:
            target = f"{info.module_path}:{var}"
            cmd = ["celery", "-A", target, "worker", "--loglevel=info"]
            candidate_commands.append(
                (
                    cmd,
                    info.rel_path,
                    f"Celery worker '{target}'",
                    ConfidenceLevel.HIGH if "celery" in deps else ConfidenceLevel.MEDIUM,
                )
            )

    # 8. Check Console Scripts in pyproject.toml
    pyproject = ctx.pyproject_data or {}
    scripts_dict: dict[str, str] = {}
    if isinstance(pyproject.get("project"), dict):
        pep_scripts = pyproject["project"].get("scripts", {})
        if isinstance(pep_scripts, dict):
            scripts_dict.update(pep_scripts)
    poetry_scripts = pyproject.get("tool", {}).get("poetry", {}).get("scripts", {})
    if isinstance(poetry_scripts, dict):
        scripts_dict.update(poetry_scripts)

    if scripts_dict and not candidate_commands:
        for script_name in sorted(scripts_dict.keys()):
            candidate_commands.append(
                (
                    [script_name],
                    "pyproject.toml",
                    f"Declared console script '{script_name}'",
                    ConfidenceLevel.HIGH,
                )
            )

    # 9. Standalone Python scripts (if __name__ == "__main__": or conventional names)
    if not candidate_commands:
        main_infos = [info for info in ast_infos if info.has_main_block]
        if main_infos:
            for info in main_infos:
                candidate_commands.append(
                    (
                        ["python", info.rel_path],
                        info.rel_path,
                        f"Python module with __main__ block in '{info.rel_path}'",
                        ConfidenceLevel.HIGH if len(main_infos) == 1 else ConfidenceLevel.MEDIUM,
                    )
                )
        else:
            for info in ast_infos:
                if info.rel_path in CONVENTIONAL_SCRIPT_NAMES or Path(info.rel_path).name in (
                    "main.py",
                    "app.py",
                    "run.py",
                ):
                    candidate_commands.append(
                        (
                            ["python", info.rel_path],
                            info.rel_path,
                            f"Conventional entry script '{info.rel_path}'",
                            ConfidenceLevel.MEDIUM,
                        )
                    )

    if not candidate_commands:
        model.entry_point.value = None
        model.entry_point.confidence = ConfidenceLevel.LOW
        model.warnings.append("Could not infer an application startup command automatically.")
        return

    unique_cmds: list[list[str]] = []
    for cmd, src, desc, conf in candidate_commands:
        model.entry_point.add_evidence(
            source=src,
            detector="entrypoint",
            description=desc,
            confidence=conf,
        )
        if cmd not in unique_cmds:
            unique_cmds.append(cmd)

    model.entry_point.candidates = unique_cmds
    chosen_cmd, _, _, chosen_conf = candidate_commands[0]
    model.entry_point.value = chosen_cmd

    if len(unique_cmds) > 1:
        model.entry_point.confidence = ConfidenceLevel.LOW
        formatted = [shlex.join(c) for c in unique_cmds]
        conflict_msg = f"Multiple plausible entry points detected: {', '.join(formatted)}"
        model.entry_point.conflicts.append(conflict_msg)
        model.warnings.append(conflict_msg)
    else:
        model.entry_point.confidence = chosen_conf
