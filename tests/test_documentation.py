"""Keep inline documentation complete without importing optional runtimes."""

import ast
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def test_project_definitions_documented():
    missing = []
    for directory in ("people_gator", "processing_api", "user_scripts"):
        for path in (ROOT / directory).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                doc = ast.get_docstring(node)
                label = f"{path.relative_to(ROOT)}:{node.lineno} {node.name}"
                if not doc:
                    missing.append(label)
                    continue
                if isinstance(node, ast.ClassDef):
                    continue
                args = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
                args += [arg for arg in (node.args.vararg, node.args.kwarg) if arg]
                for arg in args:
                    if arg.arg not in {"self", "cls"} and not re.search(
                        rf"^\s*\*{{0,2}}{arg.arg}:", doc, re.MULTILINE
                    ):
                        missing.append(f"{label}: parameter {arg.arg}")
    assert not missing, "\n".join(missing)
