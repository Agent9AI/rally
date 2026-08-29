"""Authenticated bridge from the local Rally runner to its Google ADK control plane."""
from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from typing import Dict, Optional


class CoordinatorError(RuntimeError):
    """The configured coordinator could not safely accept a commission."""


def settings(cfg: Dict) -> Dict:
    configured = dict(cfg.get("google_cloud") or {})
    env_url = os.environ.get("RALLY_CLOUD_COORDINATOR_URL", "").strip()
    if env_url:
        configured["url"] = env_url
        configured["enabled"] = True
    return configured


def is_enabled(cfg: Dict) -> bool:
    return bool(settings(cfg).get("enabled", False))


def _service_token(cloud: Dict) -> str:
    token = os.environ.get("RALLY_CLOUD_SERVICE_TOKEN", "").strip()
    if token:
        return token
    service = cloud.get("token_keychain", "rally-cloud-token")
    try:
        proc = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except Exception as exc:
        raise CoordinatorError("could not read the Cloud coordinator token") from exc
    token = proc.stdout.decode(errors="replace").strip() if proc.returncode == 0 else ""
    if not token:
        raise CoordinatorError(
            "no Cloud coordinator token: set RALLY_CLOUD_SERVICE_TOKEN or store "
            "it in the keychain as %r" % service
        )
    return token


def _identity_token(cloud: Dict) -> Optional[str]:
    if not cloud.get("google_identity", True):
        return None
    token = os.environ.get("RALLY_CLOUD_IDENTITY_TOKEN", "").strip()
    if token:
        return token
    try:
        proc = subprocess.run(
            ["gcloud", "auth", "print-identity-token"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
    except Exception as exc:
        raise CoordinatorError("could not mint a Google Cloud identity token") from exc
    token = proc.stdout.decode(errors="replace").strip() if proc.returncode == 0 else ""
    if not token:
        raise CoordinatorError(
            "no Google Cloud identity token; run `gcloud auth login imterryim@gmail.com`"
        )
    return token


def _identity_headers(cloud: Dict) -> Dict[str, str]:
    token = _identity_token(cloud)
    return {"Authorization": "Bearer " + token} if token else {}


def coordinate(cfg: Dict, task: str, run_id: str, request_key: str) -> Optional[Dict]:
    """Return the verified ADK handoff, or None when the Cloud path is disabled."""
    cloud = settings(cfg)
    if not cloud.get("enabled", False):
        return None
    base = (cloud.get("url") or "").strip().rstrip("/")
    if not base:
        raise CoordinatorError("Google Cloud coordination is enabled but its URL is unset")
    payload = json.dumps({"task": task, "run_id": run_id}).encode()
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "rally/1.0 (+https://github.com/Agent9AI/rally)",
        "X-Rally-Service-Token": _service_token(cloud),
        "Idempotency-Key": request_key,
    }
    headers.update(_identity_headers(cloud))
    req = urllib.request.Request(
        base + "/v1/commissions",
        data=payload,
        method="POST",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=int(cloud.get("timeout_sec", 180))) as response:
            record = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise CoordinatorError("coordinator returned HTTP %s: %s" % (exc.code, detail)) from exc
    except (OSError, ValueError) as exc:
        raise CoordinatorError("coordinator request failed: %s" % exc) from exc

    handoff = record.get("handoff") or {}
    policy = handoff.get("policy") or {}
    if (
        not record.get("accepted")
        or record.get("status") != "ready_for_rally"
        or record.get("run_id") != run_id
        or not policy.get("requires_independent_verification")
    ):
        raise CoordinatorError("coordinator returned an invalid or incomplete handoff")
    return record


def health(cfg: Dict) -> Optional[Dict]:
    """Read the public health endpoint without exposing the service token."""
    cloud = settings(cfg)
    if not cloud.get("enabled", False):
        return None
    base = (cloud.get("url") or "").strip().rstrip("/")
    if not base:
        raise CoordinatorError("Google Cloud coordination is enabled but its URL is unset")
    headers = {"User-Agent": "rally/1.0 (+https://github.com/Agent9AI/rally)"}
    headers.update(_identity_headers(cloud))
    req = urllib.request.Request(base + "/healthz", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.load(response)
    except (OSError, ValueError) as exc:
        raise CoordinatorError("coordinator health check failed: %s" % exc) from exc
