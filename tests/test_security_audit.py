"""Phase 7 security regression tests auditing the Dockseed source code."""

import ast
from pathlib import Path


def test_source_code_contains_no_unsafe_execution_primitives() -> None:
    """Statically verify that src/dockseed never uses eval, exec, or shell=True."""
    src_root = Path(__file__).resolve().parent.parent / "src" / "dockseed"
    py_files = sorted(src_root.rglob("*.py"))
    assert len(py_files) > 0

    for py_file in py_files:
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # 1. Forbid eval() and exec()
                if isinstance(node.func, ast.Name):
                    assert node.func.id not in (
                        "eval",
                        "exec",
                    ), f"Forbidden call '{node.func.id}()' found in {py_file}"
                # 2. Forbid subprocess(..., shell=True)
                for kw in node.keywords:
                    if kw.arg == "shell" and isinstance(kw.value, ast.Constant):
                        assert kw.value.value is False, f"Forbidden 'shell=True' found in {py_file}"
