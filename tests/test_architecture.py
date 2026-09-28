"""The dependency rule: domain <- application <- infrastructure/interfaces. Only container.py and
the interfaces may wire infrastructure in."""
import ast
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "jobhunter"
THIRD_PARTY_FORBIDDEN_IN_CORE = {"psycopg", "psycopg_pool", "openai", "supabase", "requests", "bs4", "fastapi",
                                 "googleapiclient", "google_auth_oauthlib", "jinja2", "weasyprint", "pypdf", "docx"}


def _imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    pkg = path.relative_to(PKG.parent).with_suffix("").parts[:-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = list(pkg[: len(pkg) - node.level + 1])
                yield ".".join(base + ([node.module] if node.module else []))
            else:
                yield node.module or ""


def _layer_files(layer):
    return list((PKG / layer).rglob("*.py"))


def test_domain_depends_on_nothing():
    for f in _layer_files("domain"):
        for mod in _imports(f):
            assert not mod.startswith(("jobhunter.application", "jobhunter.infrastructure", "jobhunter.interfaces",
                                       "jobhunter.container")), f"{f.name} imports {mod}"
            assert mod.split(".")[0] not in THIRD_PARTY_FORBIDDEN_IN_CORE, f"{f.name} imports {mod}"


def test_application_depends_only_on_domain():
    for f in _layer_files("application"):
        for mod in _imports(f):
            assert not mod.startswith(("jobhunter.infrastructure", "jobhunter.interfaces", "jobhunter.container")), \
                f"{f.name} imports {mod}"
            assert mod.split(".")[0] not in THIRD_PARTY_FORBIDDEN_IN_CORE, f"{f.name} imports {mod}"


def test_infrastructure_does_not_depend_on_application_or_interfaces():
    for f in _layer_files("infrastructure"):
        for mod in _imports(f):
            assert not mod.startswith(("jobhunter.application", "jobhunter.interfaces")), f"{f.name} imports {mod}"
