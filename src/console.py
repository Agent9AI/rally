"""Publish an explicitly public, sanitized view of authoritative Rally state.

The local state file contains operational details that must never reach a public
demo surface (commissioner identity, worktree paths, thread IDs, and raw cloud
records).  This module is the first allowlist.  The edge Worker applies a second
allowlist before anything is stored or returned to a browser.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import urllib.request
from typing import Dict, List, Optional

import transport


USER_AGENT = "rally/1.0 (+https://github.com/Agent9AI/rally)"
STATUSES = {"running", "complete", "blocked", "halted"}
LOCAL_MARKDOWN_FILE_LINK_RE = re.compile(
    r"\[([^\]]+)\]\(file:///[^\s)]+\)"
)
LOCAL_FILE_URL_RE = re.compile(r"file:///[^\s)\]>]+")
LOCAL_ABSOLUTE_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])/(?:Users|home|private|var/folders|tmp)/[^\s)\]>`]+"
)


class ConsoleError(RuntimeError):
    pass


def _now() -> str:
    return dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _text(value, limit: int) -> str:
    if value is None:
        return ""
    cleaned = str(value).strip()
    return cleaned[:limit]


def _redactions(state: Dict) -> List[tuple]:
    pairs = []
    for key, replacement in (
        ("workdir", "[workspace]"),
        ("commissioned_by", "[commissioner]"),
        ("thread_message_id", "[mail-id]"),
        ("commission_message_id", "[mail-id]"),
        ("commission_request_key", "[request-key]"),
    ):
        secret = state.get(key)
        if isinstance(secret, str) and len(secret) >= 4:
            pairs.append((secret, replacement))
    return sorted(pairs, key=lambda pair: len(pair[0]), reverse=True)


def _public_text(value, limit: int, redactions: List[tuple]) -> str:
    cleaned = "" if value is None else str(value).strip()
    for secret, replacement in redactions:
        cleaned = cleaned.replace(secret, replacement)
    # Model-generated reports can mention a tool's scratch directory rather
    # than the authoritative Rally workspace. Those paths are not known when
    # the run-level redaction list is assembled, so remove all common local
    # filesystem forms as a final defense before publication.
    cleaned = LOCAL_MARKDOWN_FILE_LINK_RE.sub(r"\1", cleaned)
    cleaned = LOCAL_FILE_URL_RE.sub("[local-file]", cleaned)
    cleaned = LOCAL_ABSOLUTE_PATH_RE.sub("[local-path]", cleaned)
    return cleaned[:limit]


def _title(value: str, limit: int = 100) -> str:
    first_line = (value or "").splitlines()[0].strip() or "Untitled Rally run"
    if len(first_line) <= limit:
        return first_line
    clipped = first_line[:limit - 1].rsplit(" ", 1)[0]
    return (clipped or first_line[:limit - 1]).rstrip(".,;:") + "…"


def _status(state: Dict) -> str:
    reason = ((state.get("halt") or {}).get("reason") or "").lower()
    if not reason:
        return "running"
    if reason == "complete":
        return "complete"
    if reason.startswith("blocked") or reason.startswith("disputed"):
        return "blocked"
    return "halted"


def _checklist(items: List[Dict], redactions: List[tuple]) -> List[Dict]:
    return [
        {
            "id": _text(item.get("id"), 48),
            "description": _public_text(item.get("description"), 500, redactions),
            "state": _text(item.get("state"), 40),
            "owner": _text(item.get("owner"), 40) or None,
            "verified_by": _text(item.get("verified_by"), 40) or None,
            "evidence": _public_text(item.get("evidence"), 1200, redactions) or None,
            "rejections": max(0, min(int(item.get("rejections") or 0), 99)),
        }
        for item in (items or [])[:50]
        if isinstance(item, dict)
    ]


def _changes(items: List[Dict], redactions: List[tuple]) -> List[Dict]:
    return [
        {
            "id": _text(item.get("id"), 48),
            "state": _text(item.get("state"), 40),
            "owner": _text(item.get("owner"), 40) or None,
            "verified_by": _text(item.get("verified_by"), 40) or None,
            "evidence": _public_text(item.get("evidence"), 800, redactions) or None,
        }
        for item in (items or [])[:50]
        if isinstance(item, dict)
    ]


def build_snapshot(state: Dict, cfg: Dict, published_at: Optional[str] = None) -> Dict:
    """Return the only shape the runner is allowed to publish."""
    stamp = published_at or _now()
    redactions = _redactions(state)
    checklist = _checklist(state.get("checklist") or [], redactions)
    done = sum(1 for item in checklist if item["state"] == "done")
    agents = []
    for name in ("claude", "agy"):
        agent = (cfg.get("agents") or {}).get(name) or {}
        agents.append({
            "id": name,
            "label": "Claude worker" if name == "claude" else "Gemini worker",
            "family": _text(agent.get("family"), 60),
            "model": _text(agent.get("model"), 100),
            "role": "implementation + review",
        })

    verified_items = sum(
        1 for item in checklist
        if item["state"] == "done"
        and item.get("owner")
        and item.get("verified_by")
        and item["owner"] != item["verified_by"]
    )
    evidence_receipts = sum(
        1 for item in checklist
        if item["state"] == "done" and item.get("evidence")
    )
    self_approved_items = sum(
        1 for item in checklist
        if item["state"] == "done"
        and item.get("owner")
        and item["owner"] == item.get("verified_by")
    )
    model_families = len({agent["family"] for agent in agents if agent["family"]})

    timeline = [{
        "id": "commission",
        "kind": "commission",
        "at": _text(state.get("created"), 40),
        "actor": "commissioner",
        "label": "Commission",
        "narrative": _public_text(state.get("task"), 2000, redactions),
        "changes": [],
    }]

    cloud = state.get("cloud_coordinator") or {}
    cloud_status = _text(cloud.get("status"), 60)
    if cloud_status == "ready_for_rally":
        timeline.append({
            "id": "cloud-coordination",
            "kind": "coordination",
            "at": _text(state.get("created"), 40),
            "actor": "gemini",
            "label": "Gemini coordinator",
            "narrative": _public_text(
                cloud.get("coordinator_record") or
                "Google ADK preserved the commission and issued a bounded handoff.",
                1600,
                redactions,
            ),
            "changes": [],
        })

    execution = []
    for record in (state.get("turns") or [])[-100:]:
        if not isinstance(record, dict):
            continue
        actor = _text(record.get("actor"), 40)
        execution.append({
            "id": "turn-%s-%s" % (record.get("turn", 0), actor),
            "kind": "turn",
            "at": _text(record.get("at"), 40),
            "turn": max(0, int(record.get("turn") or 0)),
            "actor": actor,
            "label": "Claude worker" if actor == "claude" else "Gemini worker",
            "family": _text(record.get("family"), 60),
            "model": _text(record.get("model"), 100),
            "narrative": _public_text(record.get("narrative"), 4000, redactions),
            "commit": _text(record.get("commit"), 64) or None,
            "changes": _changes(record.get("changes") or [], redactions),
        })

    continuity = state.get("continuity") or {}
    for record in (continuity.get("history") or [])[-20:]:
        if not isinstance(record, dict):
            continue
        source = _text(record.get("from_actor"), 40)
        target = _text(record.get("to_actor"), 40)
        items = [_text(iid, 48) for iid in (record.get("items") or [])[:20]]
        cause = (
            "a failed model turn"
            if record.get("kind") == "agent_error"
            else "a reported blocker"
        )
        narrative = (
            "Rally preserved the last accepted state after %s and handed one "
            "bounded recovery attempt from %s to %s. Independent verification "
            "remained required.%s" % (
                cause,
                "Claude" if source == "claude" else "Gemini",
                "Claude" if target == "claude" else "Gemini",
                " Recovery items: %s." % ", ".join(items) if items else "",
            )
        )
        execution.append({
            "id": _text(record.get("id"), 100),
            "kind": "recovery",
            "at": _text(record.get("at"), 40),
            "turn": max(0, int(record.get("turn") or 0)),
            "actor": "rally",
            "label": "Rally continuity",
            "family": "policy",
            "model": "Second Wind",
            "narrative": narrative,
            "commit": None,
            "changes": [],
        })

    execution.sort(key=lambda entry: (
        entry.get("at", ""), entry.get("turn", 0),
        0 if entry.get("kind") == "recovery" else 1,
    ))
    timeline.extend(execution)

    if state.get("report"):
        timeline.append({
            "id": "report",
            "kind": "report",
            "at": stamp,
            "actor": _text(state.get("actor"), 40),
            "label": "Executive report",
            "narrative": _public_text(state.get("report"), 4000, redactions),
            "changes": [],
        })

    task = _public_text(state.get("task"), 2000, redactions)
    title = _title(task)
    status = _status(state)
    assert status in STATUSES
    return {
        "schema_version": 1,
        "visibility": "public",
        "run_id": _text(state.get("run_id"), 80),
        "title": title,
        "created_at": _text(state.get("created"), 40),
        "updated_at": stamp,
        "status": status,
        "status_detail": _text((state.get("halt") or {}).get("reason"), 160),
        "turn": max(0, int(state.get("turn") or 0)),
        "next_actor": _text(state.get("actor"), 40),
        "progress": {"done": done, "total": len(checklist)},
        "value_receipt": {
            "independently_verified": verified_items,
            "evidence_receipts": evidence_receipts,
            "model_families": model_families,
            "self_approved": self_approved_items,
        },
        "policy": {
            "invariant": "owner != verified_by",
            "enforced_by": "Rally deterministic runner",
            "continuity": {
                "mode": _text(continuity.get("mode"), 40) or "halt",
                "recoveries_used": max(0, int(continuity.get("recoveries_used") or 0)),
                "max_recoveries_per_run": max(
                    0, int(continuity.get("max_recoveries_per_run") or 0)
                ),
            },
        },
        "coordination": {
            "status": cloud_status or "local",
            "framework": "Google ADK" if cloud_status == "ready_for_rally" else None,
            "services": ["Cloud Run", "Firestore"] if cloud_status == "ready_for_rally" else [],
        },
        "agents": agents,
        "checklist": checklist,
        "timeline": timeline,
        "provenance": {
            "source": "Rally authoritative runner state",
            "storage": "Cloudflare D1",
            "published_at": stamp,
        },
    }


def publish(state: Dict, cfg: Dict) -> Optional[Dict]:
    """Publish when and only when this configuration explicitly opts in."""
    settings = cfg.get("console") or {}
    if not settings.get("enabled") or not settings.get("public"):
        return None
    base = (settings.get("worker_url") or
            (cfg.get("ingress") or {}).get("worker_url") or "").rstrip("/")
    if not base:
        raise ConsoleError("console worker_url is not configured")
    run_id = _text(state.get("run_id"), 80)
    if not run_id:
        raise ConsoleError("run_id is required for console publication")
    token = transport.get_key(
        settings.get("token_keychain") or
        (cfg.get("ingress") or {}).get("poll_token_keychain", "rally-poll-token")
    )
    body = json.dumps(build_snapshot(state, cfg), separators=(",", ":")).encode()
    request = urllib.request.Request(
        "%s/v1/console/runs/%s" % (base, run_id),
        data=body,
        method="PUT",
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)
    except Exception as exc:
        raise ConsoleError("console publication failed: %s" % exc) from exc
