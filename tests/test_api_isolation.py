import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "pjm_nowcast"

FORBIDDEN = {
    "requests",
    "bs4",
    "httpx",
    "pjm_nowcast.ingest",
    "pjm_nowcast.poller",
}

SAFE_TREES = [
    ROOT / "api",
    ROOT / "mcp_facade",
    ROOT / "stats",
]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
            found.add(node.module)
    return found


def test_handlers_do_not_import_ingest_or_http_clients():
    offenders = []
    for tree in SAFE_TREES:
        for path in tree.rglob("*.py"):
            if path.name == "app.py":
                # factory may lazily start the poller; handlers themselves must not
                continue
            imported = _imports(path)
            hits = imported & FORBIDDEN
            # also catch from pjm_nowcast.ingest import X
            if any(name.startswith("pjm_nowcast.ingest") or name.startswith("pjm_nowcast.poller") for name in imported):
                hits = hits | {"pjm_nowcast.ingest"}
            if hits:
                offenders.append((str(path.relative_to(ROOT.parent)), sorted(hits)))
    assert offenders == []
