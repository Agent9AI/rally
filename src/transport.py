"""Outbound mail via Resend, with the ceiling enforced before the call.

The sending quota is shared with unrelated projects, so a runaway loop here is
someone else's outage. Every ceiling therefore fails closed: if the ledger
cannot be read, nothing sends.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional

API = "https://api.resend.com/emails"


class SendBlocked(RuntimeError):
    """Raised instead of sending. Never caught into a retry."""


def get_key(service: str = "rally-resend") -> str:
    env = os.environ.get("RESEND_API_KEY")
    if env:
        return env
    try:
        p = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10,
        )
        if p.returncode == 0:
            key = p.stdout.decode().strip()
            if key:
                return key
    except Exception:
        pass
    raise SendBlocked(
        "no Resend key: set RESEND_API_KEY or store it in the keychain as %r" % service
    )


class Ledger:
    """Send counters. Fails closed on any read problem."""

    def __init__(self, path: str):
        self.path = path

    def _read(self) -> Dict:
        if not os.path.exists(self.path):
            return {"sends": []}
        with open(self.path) as fh:
            return json.load(fh)

    def check_and_reserve(self, run_id: str, per_run: int,
                          per_hour: int = 30, per_day: int = 200) -> None:
        try:
            data = self._read()
        except Exception as exc:
            raise SendBlocked("send ledger unreadable, failing closed: %s" % exc)
        now = time.time()
        sends: List[Dict] = data.get("sends", [])
        sends = [s for s in sends if now - s.get("at", 0) < 86400]
        run_count = sum(1 for s in sends if s.get("run") == run_id)
        hour_count = sum(1 for s in sends if now - s.get("at", 0) < 3600)
        if run_count >= per_run:
            raise SendBlocked("run %s hit its %d send ceiling" % (run_id, per_run))
        if hour_count >= per_hour:
            raise SendBlocked("global hourly ceiling of %d reached" % per_hour)
        if len(sends) >= per_day:
            raise SendBlocked("global daily ceiling of %d reached" % per_day)
        sends.append({"run": run_id, "at": now})
        tmp = self.path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump({"sends": sends}, fh)
        os.replace(tmp, self.path)


def send(key: str, sender: str, to: str, subject: str, text: str,
         cc: Optional[str] = None, headers: Optional[Dict[str, str]] = None,
         reply_to: Optional[str] = None) -> str:
    payload: Dict = {"from": sender, "to": [to], "subject": subject, "text": text}
    if cc:
        payload["cc"] = [cc]
    if headers:
        payload["headers"] = headers
    if reply_to:
        payload["reply_to"] = reply_to
    req = urllib.request.Request(
        API, data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r).get("id", "")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:300]
        raise SendBlocked("resend %d: %s" % (exc.code, body))
