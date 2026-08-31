"""Read-only catalog for fleet discovery and governance evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).with_name("agent_catalog.json")


def load_catalog() -> dict[str, Any]:
    catalog = json.loads(CATALOG_PATH.read_text())
    required = {"schema_version", "catalog_version", "agents", "policy"}
    missing = required - set(catalog)
    if missing:
        raise ValueError("agent catalog is missing: " + ", ".join(sorted(missing)))
    ids = [agent.get("id") for agent in catalog["agents"]]
    if not ids or None in ids or len(ids) != len(set(ids)):
        raise ValueError("agent catalog IDs must be present and unique")
    return catalog
