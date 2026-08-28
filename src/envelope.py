"""Envelope parsing and state-machine enforcement.

The envelope an agent returns is *evidence, never authority* (SPEC section 5).
An agent proposes a new checklist; this module decides which of those proposed
transitions are legal and reverts the rest. Violations are handed back to the
agent on its next turn, so a model that tries to mark its own work done is
corrected rather than obeyed.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

STATES = {"open", "claimed", "awaiting-verification", "done", "blocked", "disputed"}
AGENTS = {"claude", "agy"}

_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def extract(text: str) -> Optional[Dict[str, Any]]:
    """Pull the envelope out of a model's reply.

    Accepts a fenced ```json block, or a bare object. Prefers the *last* fenced
    block, since models often restate an example before giving their real answer.
    """
    candidates: List[str] = _FENCE.findall(text or "")
    for blob in reversed(candidates):
        try:
            obj = json.loads(blob)
            if isinstance(obj, dict) and "checklist" in obj:
                return obj
        except json.JSONDecodeError:
            continue
    stripped = (text or "").strip()
    if stripped.startswith("{"):
        try:
            obj = json.loads(stripped)
            if isinstance(obj, dict) and "checklist" in obj:
                return obj
        except json.JSONDecodeError:
            pass
    return None


def validate_shape(env: Dict[str, Any]) -> List[str]:
    """Structural check. Returns a list of human-readable problems, empty if fine."""
    problems: List[str] = []
    if env.get("rally_version") != 1:
        problems.append("rally_version must be 1")
    if not isinstance(env.get("narrative"), str) or not env.get("narrative", "").strip():
        problems.append("narrative must be a non-empty string")
    items = env.get("checklist")
    if not isinstance(items, list) or not items:
        problems.append("checklist must be a non-empty array")
        return problems
    seen = set()
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            problems.append("checklist[%d] is not an object" % i)
            continue
        iid = it.get("id")
        if not isinstance(iid, str) or not iid:
            problems.append("checklist[%d] needs a string id" % i)
        elif iid in seen:
            problems.append("duplicate checklist id %r" % iid)
        else:
            seen.add(iid)
        if it.get("state") not in STATES:
            problems.append("checklist[%s] has invalid state %r" % (iid, it.get("state")))
        owner = it.get("owner")
        if owner is not None and owner not in AGENTS:
            problems.append("checklist[%s] has invalid owner %r" % (iid, owner))
    return problems


def _norm(it: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": it.get("id"),
        "description": it.get("description") or "",
        "state": it.get("state"),
        "owner": it.get("owner"),
        "verified_by": it.get("verified_by"),
        "evidence": it.get("evidence"),
        "rejections": int(it.get("rejections") or 0),
    }


def reconcile(
    prev: List[Dict[str, Any]],
    proposed: List[Dict[str, Any]],
    actor: str,
    rejections_max: int = 2,
    allow_new: bool = True,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Apply only the legal transitions from `proposed`, keeping `prev` otherwise.

    Returns (accepted_checklist, violations).

    The invariant that earns the second model its cost: an item may only reach
    `done` when the agent that does NOT own it says so.
    """
    other = "agy" if actor == "claude" else "claude"
    by_id = {it["id"]: _norm(it) for it in (prev or []) if it.get("id")}
    violations: List[str] = []
    out: List[Dict[str, Any]] = []
    seen: set = set()

    for raw in proposed:
        it = _norm(raw)
        iid = it["id"]
        if iid is None:
            continue
        seen.add(iid)
        old = by_id.get(iid)

        # New items belong to the negotiation phase. Observed on the first live
        # run: once work is under way, agents invent verification-of-verification
        # items ("independent re-execution", "byte-level check") and the
        # checklist regresses infinitely. Scope is agreed up front or not at all.
        if old is None:
            if not allow_new:
                violations.append(
                    "%s: scope is closed, new items are only allowed during "
                    "negotiation. Raise it in your narrative instead." % iid)
                continue
            if it["state"] not in ("open", "claimed"):
                violations.append(
                    "new item %s must start as open or claimed, not %s" % (iid, it["state"])
                )
                it["state"] = "open"
                it["owner"] = None
            out.append(it)
            continue

        was, now = old["state"], it["state"]
        owner = old["owner"]

        if was == now and owner == it["owner"]:
            merged = dict(old)
            # Evidence and description may always be enriched in place.
            merged["evidence"] = it["evidence"] or old["evidence"]
            merged["description"] = it["description"] or old["description"]
            out.append(merged)
            continue

        # --- the guarded transitions -------------------------------------
        if now == "done":
            if was != "awaiting-verification":
                violations.append(
                    "%s: done requires awaiting-verification first, was %s" % (iid, was)
                )
                out.append(old)
                continue
            if owner == actor:
                violations.append(
                    "%s: %s owns this item and cannot verify its own work" % (iid, actor)
                )
                out.append(old)
                continue
            merged = dict(old)
            merged.update(state="done", verified_by=actor,
                          evidence=it["evidence"] or old["evidence"])
            out.append(merged)
            continue

        if now == "claimed" and was == "awaiting-verification":
            # This is a rejection. Only the non-owner may reject.
            if owner == actor:
                violations.append("%s: cannot reject your own item" % iid)
                out.append(old)
                continue
            count = old["rejections"] + 1
            merged = dict(old)
            if count > rejections_max:
                merged.update(state="disputed", rejections=count,
                              evidence=it["evidence"] or old["evidence"])
            else:
                merged.update(state="claimed", rejections=count,
                              evidence=it["evidence"] or old["evidence"])
            out.append(merged)
            continue

        if now == "claimed" and was == "open":
            merged = dict(old)
            merged.update(state="claimed", owner=it["owner"] or actor)
            out.append(merged)
            continue

        if now == "awaiting-verification" and was in ("claimed", "open"):
            # Claiming and working in the same turn is legal and expected. Only
            # reaching "done" requires the other agent; forcing a separate claim
            # turn would double the turn count and spend sends for nothing.
            if owner not in (None, actor):
                violations.append(
                    "%s: owned by %s, %s may not advance it" % (iid, owner, actor)
                )
                out.append(old)
                continue
            merged = dict(old)
            merged.update(state="awaiting-verification", owner=owner or actor,
                          evidence=it["evidence"] or old["evidence"])
            out.append(merged)
            continue

        if now in ("blocked", "disputed"):
            merged = dict(old)
            merged.update(state=now, evidence=it["evidence"] or old["evidence"])
            out.append(merged)
            continue

        violations.append("%s: illegal transition %s -> %s" % (iid, was, now))
        out.append(old)

    # Items the agent silently dropped are retained; a checklist only grows.
    for iid, old in by_id.items():
        if iid not in seen:
            violations.append("%s: item was dropped from the checklist, restored" % iid)
            out.append(old)

    return out, violations


def is_complete(items: List[Dict[str, Any]]) -> bool:
    return bool(items) and all(it.get("state") == "done" for it in items)


def blocking(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [it for it in items if it.get("state") in ("blocked", "disputed")]


def digest(items: List[Dict[str, Any]]) -> str:
    """A stable fingerprint of progress, for no-progress detection."""
    return "|".join(
        "%s:%s:%s" % (it.get("id"), it.get("state"), it.get("owner"))
        for it in sorted(items, key=lambda x: str(x.get("id")))
    )
