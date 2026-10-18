"""AST-based static analysis for framework and application workload detection."""

import ast
from dataclasses import dataclass, field
from pathlib import Path

from dockseed.models import ConfidenceLevel, Framework, ProjectModel
from dockseed.scanner import ScanContext


@dataclass
class PythonFileASTInfo:
    """Extracted static AST facts from a single Python source file."""

    rel_path: str
    module_path: str
    imports: set[str] = field(default_factory=set)
    fastapi_vars: list[str] = field(default_factory=list)
    flask_vars: list[str] = field(default_factory=list)
    celery_vars: list[str] = field(default_factory=list)
    factory_funcs: dict[str, Framework] = field(default_factory=dict)
    has_main_block: bool = False
    has_streamlit_calls: bool = False
    has_gradio_launch: bool = False
    has_cli_usage: bool = False


def path_to_module(rel_posix: str) -> str:
    """Convert a relative POSIX file path into a dotted Python module path."""
    p = Path(rel_posix)
    parts = list(p.with_suffix("").parts)
    if parts and parts[0] == "src" and len(parts) > 1:
        parts = parts[1:]
    if parts and parts[-1] == "__init__" and len(parts) > 1:
        parts = parts[:-1]
    return ".".join(parts)


def _get_call_name(node: ast.Call) -> str | None:
    """Return the simple function/class name being called (e.g., 'FastAPI' or 'st.title')."""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        if isinstance(node.func.value, ast.Name):
            return f"{node.func.value.id}.{node.func.attr}"
        return node.func.attr
    return None


def _is_main_guard(node: ast.If) -> bool:
    """Return True if an ast.If node is `if __name__ == '__main__':`."""
    test = node.test
    if not isinstance(test, ast.Compare) or len(test.ops) != 1 or len(test.comparators) != 1:
        return False
    if not isinstance(test.ops[0], ast.Eq):
        return False
    left, right = test.left, test.comparators[0]
    if (
        isinstance(left, ast.Name)
        and left.id == "__name__"
        and isinstance(right, ast.Constant)
        and right.value == "__main__"
    ):
        return True
    return (
        isinstance(right, ast.Name)
        and right.id == "__name__"
        and isinstance(left, ast.Constant)
        and left.value == "__main__"
    )


def analyze_python_file(rel_posix: str, source_code: str) -> PythonFileASTInfo | None:
    """Parse a Python file into an AST and extract framework and entrypoint signals."""
    try:
        tree = ast.parse(source_code, filename=rel_posix)
    except SyntaxError:
        return None

    info = PythonFileASTInfo(rel_path=rel_posix, module_path=path_to_module(rel_posix))

    # Inspect top-level statements and function definitions safely
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_pkg = alias.name.split(".")[0].lower()
                info.imports.add(top_pkg)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_pkg = node.module.split(".")[0].lower()
            info.imports.add(top_pkg)
        elif isinstance(node, ast.If) and _is_main_guard(node):
            info.has_main_block = True
        elif isinstance(node, ast.Call):
            call_name = _get_call_name(node)
            if call_name:
                if call_name.startswith(("st.", "streamlit.")):
                    info.has_streamlit_calls = True
                elif call_name.endswith(".launch") or call_name in (
                    "gr.Interface",
                    "gr.Blocks",
                    "Interface",
                    "Blocks",
                ):
                    if "gradio" in info.imports:
                        info.has_gradio_launch = True
                elif call_name in (
                    "typer.Typer",
                    "Typer",
                    "argparse.ArgumentParser",
                    "ArgumentParser",
                    "click.command",
                    "click.group",
                ):
                    info.has_cli_usage = True

    # Inspect module-level assignments and app factory functions
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign | ast.AnnAssign):
            value = stmt.value
            targets = (
                stmt.targets
                if isinstance(stmt, ast.Assign)
                else ([stmt.target] if stmt.value is not None else [])
            )
            if isinstance(value, ast.Call):
                call_name = _get_call_name(value)
                for target in targets:
                    if isinstance(target, ast.Name):
                        var_name = target.id
                        if call_name in ("FastAPI", "fastapi.FastAPI"):
                            info.fastapi_vars.append(var_name)
                        elif call_name in ("Flask", "flask.Flask"):
                            info.flask_vars.append(var_name)
                        elif call_name in ("Celery", "celery.Celery"):
                            info.celery_vars.append(var_name)
        elif isinstance(stmt, ast.FunctionDef):
            for sub in ast.walk(stmt):
                if isinstance(sub, ast.Call):
                    cname = _get_call_name(sub)
                    if cname in ("FastAPI", "fastapi.FastAPI"):
                        info.factory_funcs[stmt.name] = Framework.FASTAPI
                    elif cname in ("Flask", "flask.Flask"):
                        info.factory_funcs[stmt.name] = Framework.FLASK

    return info


def scan_python_sources(ctx: ScanContext) -> list[PythonFileASTInfo]:
    """Scan all non-test Python files in the project using static AST parsing."""
    results: list[PythonFileASTInfo] = []
    for rel_path in ctx.files:
        if rel_path.suffix != ".py":
            continue
        parts = rel_path.parts
        if any(p in ("tests", "test", "docs", "migrations") for p in parts):
            continue
        if rel_path.name.startswith("test_") or rel_path.name.endswith("_test.py"):
            continue

        raw = ctx.read_text_safe(rel_path.as_posix())
        if raw is None:
            continue

        info = analyze_python_file(rel_path.as_posix(), raw)
        if info is None:
            ctx.warnings.append(
                f"Skipped AST analysis of '{rel_path.as_posix()}' due to syntax error."
            )
            continue
        results.append(info)

    return results


def detect_framework(
    ctx: ScanContext,
    model: ProjectModel,
    ast_infos: list[PythonFileASTInfo],
) -> None:
    """Determine the primary application framework using dependencies and AST evidence."""
    deps = set(model.runtime_dependencies)
    candidates: list[tuple[Framework, str, str, ConfidenceLevel]] = []

    # 1. Django detection (manage.py + django dependency or imports)
    has_manage_py = ctx.has_file("manage.py") or any(f.name == "manage.py" for f in ctx.files)
    has_django_import = any("django" in info.imports for info in ast_infos)
    if has_manage_py and ("django" in deps or has_django_import):
        candidates.append(
            (
                Framework.DJANGO,
                "manage.py",
                "Found Django manage.py and django dependency/imports",
                ConfidenceLevel.HIGH,
            )
        )
    elif "django" in deps and has_django_import:
        candidates.append(
            (
                Framework.DJANGO,
                "pyproject.toml/requirements",
                "Found django dependency and source imports",
                ConfidenceLevel.MEDIUM,
            )
        )

    # 2. FastAPI detection
    fastapi_files = [
        info
        for info in ast_infos
        if info.fastapi_vars or Framework.FASTAPI in info.factory_funcs.values()
    ]
    if fastapi_files:
        conf = ConfidenceLevel.HIGH if "fastapi" in deps else ConfidenceLevel.MEDIUM
        candidates.append(
            (
                Framework.FASTAPI,
                fastapi_files[0].rel_path,
                f"Found FastAPI application instance in '{fastapi_files[0].rel_path}'",
                conf,
            )
        )

    # 3. Flask detection
    flask_files = [
        info
        for info in ast_infos
        if info.flask_vars or Framework.FLASK in info.factory_funcs.values()
    ]
    if flask_files:
        conf = ConfidenceLevel.HIGH if "flask" in deps else ConfidenceLevel.MEDIUM
        candidates.append(
            (
                Framework.FLASK,
                flask_files[0].rel_path,
                f"Found Flask application instance in '{flask_files[0].rel_path}'",
                conf,
            )
        )

    # 4. Streamlit detection
    st_files = [
        info for info in ast_infos if "streamlit" in info.imports or info.has_streamlit_calls
    ]
    if st_files:
        conf = ConfidenceLevel.HIGH if "streamlit" in deps else ConfidenceLevel.MEDIUM
        candidates.append(
            (
                Framework.STREAMLIT,
                st_files[0].rel_path,
                f"Found Streamlit usage in '{st_files[0].rel_path}'",
                conf,
            )
        )

    # 5. Gradio detection
    gr_files = [info for info in ast_infos if "gradio" in info.imports or info.has_gradio_launch]
    if gr_files:
        conf = ConfidenceLevel.HIGH if "gradio" in deps else ConfidenceLevel.MEDIUM
        candidates.append(
            (
                Framework.GRADIO,
                gr_files[0].rel_path,
                f"Found Gradio interface in '{gr_files[0].rel_path}'",
                conf,
            )
        )

    # 6. Celery / Background Worker detection
    celery_files = [info for info in ast_infos if info.celery_vars]
    if celery_files:
        conf = ConfidenceLevel.HIGH if "celery" in deps else ConfidenceLevel.MEDIUM
        candidates.append(
            (
                Framework.CELERY,
                celery_files[0].rel_path,
                f"Found Celery worker instance in '{celery_files[0].rel_path}'",
                conf,
            )
        )

    # 7. CLI detection (declared console scripts or click/typer/argparse AST signals)
    pyproject = ctx.pyproject_data or {}
    has_pep621_scripts = bool(
        isinstance(pyproject.get("project"), dict) and pyproject["project"].get("scripts")
    )
    has_poetry_scripts = bool(pyproject.get("tool", {}).get("poetry", {}).get("scripts"))
    cli_files = [info for info in ast_infos if info.has_cli_usage]

    if has_pep621_scripts or has_poetry_scripts:
        candidates.append(
            (
                Framework.CLI,
                "pyproject.toml",
                "Found console script entry points in pyproject.toml",
                ConfidenceLevel.HIGH,
            )
        )
    elif cli_files and not candidates:
        candidates.append(
            (
                Framework.CLI,
                cli_files[0].rel_path,
                f"Found CLI parser usage in '{cli_files[0].rel_path}'",
                ConfidenceLevel.MEDIUM,
            )
        )

    # 8. Standalone Python script fallback
    main_files = [info for info in ast_infos if info.has_main_block]
    if not candidates and (main_files or ast_infos):
        target_info = main_files[0] if main_files else ast_infos[0]
        conf = ConfidenceLevel.MEDIUM if main_files else ConfidenceLevel.LOW
        candidates.append(
            (
                Framework.SCRIPT,
                target_info.rel_path,
                f"Detected standalone Python script '{target_info.rel_path}'",
                conf,
            )
        )

    if not candidates:
        model.framework.value = Framework.UNKNOWN
        model.framework.confidence = ConfidenceLevel.LOW
        return

    unique_frameworks: list[Framework] = []
    for fw, src, desc, conf in candidates:
        model.framework.add_evidence(
            source=src,
            detector="framework",
            description=desc,
            confidence=conf,
        )
        if fw not in unique_frameworks:
            unique_frameworks.append(fw)

    model.framework.candidates = unique_frameworks
    chosen_fw, _, _, chosen_conf = candidates[0]
    model.framework.value = chosen_fw
    model.framework.confidence = chosen_conf
