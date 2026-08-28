"""Inbound: collect mail from the ingress Worker and turn it into runs.

The Worker holds messages durably because this process runs on a machine that
sleeps. Nothing here trusts the message: authority to commission a run comes from
the verified sender address, never from anything the body asks for.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Tuple

import transport

RESEND_INBOUND = "https://api.resend.com/emails/inbound/%s"
RUN_TAG = re.compile(r"\[rally\s+#(r-[0-9a-z-]+)", re.IGNORECASE)


def _get(url: str, token: str, timeout: int = 25) -> Dict:
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _post(url: str, token: str, body: Dict, timeout: int = 25) -> Dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def find_email_id(payload: Dict) -> Optional[str]:
    """Resend nests the id differently across webhook versions. Accept both."""
    if not isinstance(payload, dict):
        return None
    if payload.get("email_id"):
        return payload["email_id"]
    data = payload.get("data")
    if isinstance(data, dict) and data.get("email_id"):
        return data["email_id"]
    if isinstance(data, dict) and data.get("id"):
        return data["id"]
    return payload.get("id")


def fetch_message(email_id: str, resend_key: str) -> Dict:
    return _get(RESEND_INBOUND % email_id, resend_key)


def addresses(value) -> List[str]:
    """Normalise Resend's to/from, which may be a string or a list."""
    out: List[str] = []
    items = value if isinstance(value, list) else [value]
    for v in items:
        if not v:
            continue
        s = v if isinstance(v, str) else (v.get("email") or "")
        m = re.search(r"[\w.+-]+@[\w.-]+", s)
        if m:
            out.append(m.group(0).lower())
    return out


def strip_quoted(text: str) -> str:
    """Drop the quoted chain, so thread depth does not inflate the task."""
    lines: List[str] = []
    for line in (text or "").splitlines():
        if line.startswith(">"):
            continue
        if re.match(r"^\s*On .+ wrote:\s*$", line):
            break
        if line.strip() in ("--", "---") and len(lines) > 3:
            break
        lines.append(line)
    return "\n".join(lines).strip()


def classify(msg: Dict, cfg: Dict) -> Tuple[str, Dict]:
    """Decide what an inbound message is. Returns (kind, details).

    kind is one of: commission, note, ignored.
    """
    ing = cfg["ingress"]
    owners = {a.lower() for a in ing.get("owners", [])}
    sender = (addresses(msg.get("from")) or [""])[0]
    to = set(addresses(msg.get("to")) + addresses(msg.get("cc")))
    subject = msg.get("subject") or ""
    body = strip_quoted(msg.get("text") or "")

    if sender not in owners:
        # Authority comes from the verified sender, never from the body.
        return "ignored", {"why": "sender %s is not an owner" % sender}

    tagged = RUN_TAG.search(subject)
    if tagged:
        return "note", {"run_id": tagged.group(1), "text": body, "sender": sender}

    if ing["commission_address"].lower() in to:
        if not body:
            return "ignored", {"why": "empty commission body"}
        return "commission", {"task": body, "subject": subject, "sender": sender}

    return "ignored", {"why": "not addressed to the commission address"}


def collect(cfg: Dict) -> List[Dict]:
    """Pull pending messages from the Worker and hydrate them from Resend."""
    ing = cfg["ingress"]
    base = (ing.get("worker_url") or "").rstrip("/")
    if not base:
        raise RuntimeError("ingress.worker_url is not configured")
    poll_token = transport.get_key(ing.get("poll_token_keychain", "rally-poll-token"))
    resend_key = transport.get_key(cfg["mail"].get("keychain_service", "rally-resend"))

    pending = _get(base + "/pending", poll_token).get("messages", [])
    out: List[Dict] = []
    for rec in pending:
        eid = find_email_id(rec.get("payload") or {})
        if not eid:
            out.append({"id": rec["id"], "error": "no email_id in payload"})
            continue
        try:
            msg = fetch_message(eid, resend_key)
        except urllib.error.HTTPError as exc:
            out.append({"id": rec["id"], "error": "resend %d" % exc.code})
            continue
        kind, detail = classify(msg, cfg)
        out.append({"id": rec["id"], "kind": kind, "detail": detail,
                    "subject": msg.get("subject"), "from": msg.get("from")})
    return out


def ack(cfg: Dict, ids: List[str]) -> None:
    if not ids:
        return
    ing = cfg["ingress"]
    base = ing["worker_url"].rstrip("/")
    poll_token = transport.get_key(ing.get("poll_token_keychain", "rally-poll-token"))
    _post(base + "/ack", poll_token, {"ids": ids})
