"""Each module's __init__.py is its whole public surface. Fails if code imports another module's
internals (e.g. `from app.record.critic import ...` outside app/record). Also enforces that only
app.worldmodel touches the engine, so the World Model stays the single writer of domain tables."""
from __future__ import annotations

import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
MODULES = {"record", "trials", "matching", "enquiry", "worldmodel", "trace", "llm", "sql", "api", "extraction"}
# Shared plumbing that any module may import directly.
ALLOWED = {"app.sql.reader", "app.sql.writer", "app.trace.events", "app.trace.state", "app.llm.nightshift"}
IMPORT = re.compile(r"^\s*from\s+(app\.[\w.]+)\s+import", re.M)


def owner(path: Path) -> str | None:
    rel = path.relative_to(APP).parts
    return rel[0] if rel and rel[0] in MODULES else None


def test_no_cross_module_internal_imports():
    violations = []
    for path in APP.rglob("*.py"):
        mine = owner(path)
        for target in IMPORT.findall(path.read_text()):
            parts = target.split(".")
            if len(parts) < 3 or parts[1] not in MODULES or parts[1] == mine or target in ALLOWED:
                continue
            violations.append(f"{path.relative_to(APP)} imports {target}")
    assert not violations, "import the module's facade instead:\n" + "\n".join(violations)
