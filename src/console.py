"""Publish a sanitized workspace view of authoritative Rally state.

The local state file contains operational details that must never reach a public
or private browser surface (commissioner identity, worktree paths, thread IDs,
and raw cloud records).  This module is the first allowlist.  The edge Worker
applies a second allowlist and scopes private records to an authenticated
workspace before anything is returned to a browser.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import stat
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

import transport


USER_AGENT = "rally/1.0 (+https://github.com/Agent9AI/rally)"
STATUSES = {"running", "complete", "blocked", "halted"}
WORKSPACE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$")
LOCAL_MARKDOWN_FILE_LINK_RE = re.compile(
    r"\[([^\]]+)\]\(file:///[^\s)]+\)"
)
LOCAL_FILE_URL_RE = re.compile(r"file:///[^\s)\]>]+")
LOCAL_ABSOLUTE_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])/(?:Users|home|private|var/folders|tmp)/[^\s)\]>`]+"
)
ARTIFACT_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
ARTIFACT_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_ARTIFACT_FILE_BYTES = 6 * 1024 * 1024
MAX_ARTIFACT_TOTAL_BYTES = 8 * 1024 * 1024
MAX_ARTIFACTS = 5


class ConsoleError(RuntimeError):
    pass


def validate_workspace_id(value) -> str:
    """Return one workspace identifier after applying the console boundary."""
    candidate = value.strip() if isinstance(value, str) else ""
    if not WORKSPACE_ID_RE.fullmatch(candidate):
        raise ConsoleError("console workspace_id is not configured")
    return candidate


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


def _independently_complete(state: Dict) -> bool:
    """Return true only after every accepted item has independent sign-off."""
    checklist = state.get("checklist") or []
    return (
        _status(state) == "complete"
        and bool(checklist)
        and all(
            isinstance(item, dict)
            and item.get("state") == "done"
            and item.get("owner")
            and item.get("verified_by")
            and item.get("owner") != item.get("verified_by")
            for item in checklist
        )
    )


def _artifact_workspace(state: Dict) -> Optional[str]:
    """Resolve the isolated run workspace without trusting a stored path."""
    run_id = _text(state.get("run_id"), 80)
    if not re.fullmatch(r"r-[0-9a-z-]{3,77}", run_id):
        return None
    runs_root = os.path.realpath(transport.RUNS_ROOT)
    run_candidate = os.path.join(runs_root, run_id)
    if os.path.islink(run_candidate) or not os.path.isdir(run_candidate):
        return None
    run_root = os.path.realpath(run_candidate)
    try:
        if os.path.commonpath((runs_root, run_root)) != runs_root:
            return None
    except ValueError:
        return None
    workspace = os.path.join(run_root, "workspace")
    if os.path.islink(workspace) or not os.path.isdir(workspace):
        return None
    workspace_real = os.path.realpath(workspace)
    if not workspace_real.startswith(run_root + os.sep):
        return None
    return workspace_real


def _read_artifact(state: Dict, filename: str) -> Optional[bytes]:
    """Read one bounded regular file without following a symlink."""
    workspace = _artifact_workspace(state)
    if not workspace or not ARTIFACT_FILENAME_RE.fullmatch(filename or ""):
        return None
    path = os.path.join(workspace, filename)
    if os.path.realpath(path) != path or not os.path.realpath(path).startswith(workspace + os.sep):
        return None
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_size <= 0
            or info.st_size > MAX_ARTIFACT_FILE_BYTES
        ):
            return None
        chunks = []
        remaining = MAX_ARTIFACT_FILE_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        if len(content) != info.st_size or len(content) > MAX_ARTIFACT_FILE_BYTES:
            return None
        if transport._looks_secret(filename, content):
            return None
        return content
    finally:
        os.close(descriptor)


def _artifact_kind(receipt: Dict, mime_type: str) -> Optional[str]:
    requested = _text(receipt.get("kind"), 20).lower()
    if requested == "song" and mime_type.startswith("audio/"):
        return "audio"
    if requested == "image" and mime_type.startswith("image/"):
        return "image"
    return None


def _verified_artifacts(state: Dict, status: str = "staged") -> List[Dict]:
    """Return bounded metadata for locally present, independently verified media."""
    if status not in {"staged", "ready"}:
        raise ConsoleError("artifact status is invalid")
    if not _independently_complete(state):
        return []
    artifacts = []
    seen = set()
    total = 0
    for receipt in (state.get("media_generations") or [])[-MAX_ARTIFACTS:]:
        if not isinstance(receipt, dict) or receipt.get("status") != "ready":
            continue
        filename = _text(receipt.get("filename"), 96)
        sha256 = _text(receipt.get("sha256"), 64).lower()
        mime_type = _text(receipt.get("mime_type"), 100).lower()
        if (
            filename in seen
            or not ARTIFACT_FILENAME_RE.fullmatch(filename)
            or not ARTIFACT_SHA256_RE.fullmatch(sha256)
        ):
            continue
        extension = os.path.splitext(filename)[1].lower()
        expected_mime = transport.ATTACHMENT_TYPES.get(extension)
        if not expected_mime or expected_mime != mime_type:
            continue
        kind = _artifact_kind(receipt, mime_type)
        if not kind:
            continue
        content = _read_artifact(state, filename)
        if not content or hashlib.sha256(content).hexdigest() != sha256:
            continue
        try:
            receipt_size = int(receipt.get("bytes"))
        except (TypeError, ValueError):
            continue
        if receipt_size != len(content) or total + len(content) > MAX_ARTIFACT_TOTAL_BYTES:
            continue
        seen.add(filename)
        total += len(content)
        artifacts.append({
            "filename": filename,
            "label": "Generated song" if kind == "audio" else "Generated image",
            "mime_type": mime_type,
            "size_bytes": len(content),
            "sha256": sha256,
            "kind": kind,
            "status": status,
        })
    return artifacts


def _agent_label(name: str) -> str:
    return {
        "claude": "Claude worker",
        "agy": "Gemini worker",
        "codex": "OpenAI worker",
    }.get(name, "%s worker" % (name or "Unknown").title())


def build_snapshot(
    state: Dict,
    cfg: Dict,
    published_at: Optional[str] = None,
    artifact_status: str = "staged",
) -> Dict:
    """Return the only shape the runner is allowed to publish."""
    stamp = published_at or _now()
    settings = cfg.get("console") or {}
    # Dashboard commissions carry an authenticated workspace all the way into
    # authoritative run state. Only legacy email and direct CLI runs (which do
    # not have the field at all) may fall back to the configured workspace.
    workspace_id = validate_workspace_id(
        state["workspace_id"]
        if "workspace_id" in state
        else settings.get("workspace_id")
    )
    redactions = _redactions(state)
    checklist = _checklist(state.get("checklist") or [], redactions)
    done = sum(1 for item in checklist if item["state"] == "done")
    participants = {
        _text(record.get("actor"), 40)
        for record in (state.get("turns") or [])
        if isinstance(record, dict) and record.get("actor")
    }
    agents = []
    for name, agent in (cfg.get("agents") or {}).items():
        agents.append({
            "id": name,
            "label": _agent_label(name),
            "family": _text(agent.get("family"), 60),
            "model": _text(agent.get("model"), 100),
            "role": "implementation + review",
            "participated": name in participants,
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
    model_families = len({
        agent["family"] for agent in agents
        if agent["family"] and agent["participated"]
    })

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
            "label": _agent_label(actor),
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
                _agent_label(source).replace(" worker", ""),
                _agent_label(target).replace(" worker", ""),
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
        # The Worker hashes workspace_id before storage and removes it from the
        # browser payload. Public visibility remains a separate explicit opt-in.
        "workspace_id": workspace_id,
        "visibility": "public" if settings.get("public") else "private",
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
        "artifacts": _verified_artifacts(state, artifact_status),
        "checklist": checklist,
        "timeline": timeline,
        "provenance": {
            "source": "Rally authoritative runner state",
            "storage": "Cloudflare D1",
            "published_at": stamp,
        },
    }


def publish(state: Dict, cfg: Dict) -> Optional[Dict]:
    """Publish an allowlisted projection when workspace sync is enabled."""
    settings = cfg.get("console") or {}
    if not settings.get("enabled"):
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
    snapshot = build_snapshot(state, cfg, artifact_status="staged")

    def publish_projection(projection: Dict) -> Dict:
        request = urllib.request.Request(
            "%s/v1/console/runs/%s" % (base, run_id),
            data=json.dumps(projection, separators=(",", ":")).encode(),
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

    result = publish_projection(snapshot)
    for artifact in snapshot["artifacts"]:
        content = _read_artifact(state, artifact["filename"])
        if (
            content is None
            or len(content) != artifact["size_bytes"]
            or hashlib.sha256(content).hexdigest() != artifact["sha256"]
        ):
            raise ConsoleError("console artifact changed before upload")
        artifact_request = urllib.request.Request(
            "%s/v1/console/artifacts/%s/%s" % (
                base,
                urllib.parse.quote(run_id, safe=""),
                urllib.parse.quote(artifact["filename"], safe=""),
            ),
            data=content,
            method="PUT",
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": artifact["mime_type"],
                "Content-Length": str(artifact["size_bytes"]),
                "X-Rally-Artifact-SHA256": artifact["sha256"],
                "X-Rally-Artifact-Kind": artifact["kind"],
                "X-Rally-Artifact-Label": artifact["label"],
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(artifact_request, timeout=30) as response:
                response.read()
        except Exception as exc:
            raise ConsoleError("console artifact upload failed") from exc
    if snapshot["artifacts"]:
        ready_snapshot = dict(snapshot)
        ready_snapshot["artifacts"] = [
            {**artifact, "status": "ready"}
            for artifact in snapshot["artifacts"]
        ]
        result = publish_projection(ready_snapshot)
    return result
