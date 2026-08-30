"""Private, single-use approval ledger for connector tool calls.

The ledger is a bounded local-demo sidecar. Exact tool arguments stay in its
private file; callers receive only content-free receipt dictionaries. Every
state transition is serialized with ``flock`` and committed with an atomic
replace so separate Rally processes cannot consume one approval twice.
"""

from __future__ import annotations

import copy
import fcntl
import hashlib
import hmac
import json
import os
import secrets
import stat
import tempfile
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

SCHEMA_VERSION = "rally.connector-approval-ledger/v1"
STATUSES = frozenset({"pending", "approved", "consumed", "expired"})
DEFAULT_TTL_SECONDS = 300
MAX_TTL_SECONDS = 3600
MAX_RECORDS = 1024
MAX_ARGUMENT_BYTES = 256 * 1024
MAX_IDENTIFIER_LENGTH = 256


class ApprovalError(RuntimeError):
    """Base class for safe, expected approval-ledger failures."""


class ApprovalInputError(ApprovalError):
    """The caller supplied invalid approval data."""


class ApprovalNotFound(ApprovalError):
    """No approval exists with the requested identifier."""


class ApprovalStateError(ApprovalError):
    """The requested transition is illegal for the approval's state."""


class ApprovalExpired(ApprovalStateError):
    """The approval expired before the requested transition."""


class ApprovalReplay(ApprovalStateError):
    """A consumed approval was presented again."""


class ApprovalMismatch(ApprovalError):
    """A consume request does not exactly match the approved request."""


class ApprovalLimitError(ApprovalError):
    """The bounded ledger has no room for another active request."""


class ApprovalLedgerCorrupt(ApprovalError):
    """The private ledger is malformed or internally inconsistent."""


T = TypeVar("T")


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ApprovalInputError("connector arguments must be finite JSON data") from exc


def canonical_arguments_sha256(arguments: Mapping[str, Any]) -> str:
    """Return the stable SHA-256 bound into an approval request."""
    if not isinstance(arguments, Mapping):
        raise ApprovalInputError("connector arguments must be a JSON object")
    encoded = _canonical_json(dict(arguments)).encode("utf-8")
    if len(encoded) > MAX_ARGUMENT_BYTES:
        raise ApprovalInputError(
            f"connector arguments exceed the {MAX_ARGUMENT_BYTES}-byte approval limit"
        )
    return hashlib.sha256(encoded).hexdigest()


def _private_arguments(arguments: Mapping[str, Any]) -> dict[str, Any]:
    canonical = _canonical_json(dict(arguments))
    if len(canonical.encode("utf-8")) > MAX_ARGUMENT_BYTES:
        raise ApprovalInputError(
            f"connector arguments exceed the {MAX_ARGUMENT_BYTES}-byte approval limit"
        )
    # The JSON round trip both detaches caller-owned objects and preserves the
    # exact JSON value whose canonical form is hashed.
    return json.loads(canonical)


def _identifier(value: str, label: str) -> str:
    if not isinstance(value, str):
        raise ApprovalInputError(f"{label} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > MAX_IDENTIFIER_LENGTH or "\x00" in normalized:
        raise ApprovalInputError(f"{label} is empty or too long")
    return normalized


def _instant(value: datetime | None = None) -> datetime:
    current = value or datetime.now(UTC)
    if not isinstance(current, datetime) or current.tzinfo is None:
        raise ApprovalInputError("approval timestamps must be timezone-aware")
    return current.astimezone(UTC)


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise ApprovalLedgerCorrupt(f"{label} is not an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ApprovalLedgerCorrupt(f"{label} is not an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ApprovalLedgerCorrupt(f"{label} is not timezone-aware")
    return parsed.astimezone(UTC)


def _empty_ledger() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "requests": {}}


def _validate_record(approval_id: str, record: Any) -> None:
    if not isinstance(record, dict):
        raise ApprovalLedgerCorrupt(f"approval {approval_id} is not an object")
    required = {
        "approval_id",
        "status",
        "run_id",
        "connector_id",
        "tool_name",
        "arguments_sha256",
        "arguments",
        "created_at",
        "expires_at",
    }
    if not required.issubset(record) or record.get("approval_id") != approval_id:
        raise ApprovalLedgerCorrupt(f"approval {approval_id} is missing required fields")
    if record.get("status") not in STATUSES:
        raise ApprovalLedgerCorrupt(f"approval {approval_id} has an invalid status")
    _parse_timestamp(record["created_at"], "created_at")
    _parse_timestamp(record["expires_at"], "expires_at")
    try:
        actual_hash = canonical_arguments_sha256(record["arguments"])
    except ApprovalInputError as exc:
        raise ApprovalLedgerCorrupt(f"approval {approval_id} has invalid arguments") from exc
    stored_hash = record.get("arguments_sha256")
    if not isinstance(stored_hash, str) or not hmac.compare_digest(stored_hash, actual_hash):
        raise ApprovalLedgerCorrupt(f"approval {approval_id} argument hash does not match")


def _load_ledger(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _empty_ledger()
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ApprovalLedgerCorrupt(f"cannot open approval ledger: {exc}") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ApprovalLedgerCorrupt("approval ledger is not a regular file")
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, encoding="utf-8") as handle:
            descriptor = -1
            value = json.load(handle)
    except (OSError, ValueError) as exc:
        raise ApprovalLedgerCorrupt(f"cannot read approval ledger: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise ApprovalLedgerCorrupt("unsupported approval ledger schema")
    requests = value.get("requests")
    if not isinstance(requests, dict):
        raise ApprovalLedgerCorrupt("approval ledger requests must be an object")
    for approval_id, record in requests.items():
        _validate_record(approval_id, record)
    return value


def _atomic_write(path: Path, ledger: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(ledger, handle, ensure_ascii=False, allow_nan=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        os.chmod(path, 0o600)
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_descriptor = os.open(path.parent, directory_flags)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


@contextmanager
def _exclusive_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ApprovalLedgerCorrupt("approval lock is not a regular file")
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _expire(ledger: dict[str, Any], now: datetime) -> bool:
    changed = False
    for record in ledger["requests"].values():
        if record["status"] in {"pending", "approved"} and now >= _parse_timestamp(
            record["expires_at"], "expires_at"
        ):
            record["status"] = "expired"
            record["expired_at"] = _timestamp(now)
            changed = True
    return changed


def _terminal_time(record: dict[str, Any]) -> datetime:
    for field in ("consumed_at", "expired_at", "expires_at", "created_at"):
        if record.get(field):
            return _parse_timestamp(record[field], field)
    raise ApprovalLedgerCorrupt("approval has no usable timestamp")


def _make_space(ledger: dict[str, Any]) -> None:
    requests = ledger["requests"]
    needed = len(requests) - MAX_RECORDS + 1
    if needed <= 0:
        return
    terminal = sorted(
        (
            (approval_id, record)
            for approval_id, record in requests.items()
            if record["status"] in {"consumed", "expired"}
        ),
        key=lambda item: (_terminal_time(item[1]), item[0]),
    )
    for approval_id, _ in terminal[:needed]:
        del requests[approval_id]
    if len(requests) >= MAX_RECORDS:
        raise ApprovalLimitError(f"approval ledger already contains {MAX_RECORDS} active requests")


def _transaction(
    ledger_path: str | os.PathLike[str],
    now: datetime,
    operation: Callable[[dict[str, Any]], tuple[T, bool]],
) -> T:
    path = Path(ledger_path)
    with _exclusive_lock(path):
        ledger = _load_ledger(path)
        changed = _expire(ledger, now)
        try:
            result, operation_changed = operation(ledger)
        except Exception:
            if changed:
                _atomic_write(path, ledger)
            raise
        if changed or operation_changed:
            _atomic_write(path, ledger)
        return result


def public_receipt(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return audit metadata without the private argument payload."""
    fields = (
        "approval_id",
        "status",
        "run_id",
        "connector_id",
        "tool_name",
        "arguments_sha256",
        "created_at",
        "expires_at",
        "approved_at",
        "approved_by",
        "consumed_at",
        "expired_at",
    )
    return {field: copy.deepcopy(record[field]) for field in fields if field in record}


def request_approval(
    ledger_path: str | os.PathLike[str],
    *,
    run_id: str,
    connector_id: str,
    tool_name: str,
    arguments: Mapping[str, Any],
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Create a private pending request and return its content-free receipt."""
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int):
        raise ApprovalInputError("approval TTL must be an integer number of seconds")
    if ttl_seconds < 1 or ttl_seconds > MAX_TTL_SECONDS:
        raise ApprovalInputError(f"approval TTL must be between 1 and {MAX_TTL_SECONDS} seconds")
    current = _instant(now)
    private_arguments = _private_arguments(arguments)
    argument_hash = canonical_arguments_sha256(private_arguments)
    record = {
        "approval_id": "apr_" + secrets.token_hex(16),
        "status": "pending",
        "run_id": _identifier(run_id, "run_id"),
        "connector_id": _identifier(connector_id, "connector_id"),
        "tool_name": _identifier(tool_name, "tool_name"),
        "arguments_sha256": argument_hash,
        "arguments": private_arguments,
        "created_at": _timestamp(current),
        "expires_at": _timestamp(current + timedelta(seconds=ttl_seconds)),
    }

    def create(ledger: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        _make_space(ledger)
        while record["approval_id"] in ledger["requests"]:
            record["approval_id"] = "apr_" + secrets.token_hex(16)
        ledger["requests"][record["approval_id"]] = record
        return public_receipt(record), True

    return _transaction(ledger_path, current, create)


def get_for_review(
    ledger_path: str | os.PathLike[str],
    approval_id: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return one private record to the trusted human-approval interface."""
    current = _instant(now)
    requested_id = _identifier(approval_id, "approval_id")

    def read(ledger: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        record = ledger["requests"].get(requested_id)
        if record is None:
            raise ApprovalNotFound(f"approval {requested_id} does not exist")
        return copy.deepcopy(record), False

    return _transaction(ledger_path, current, read)


def list_public(
    ledger_path: str | os.PathLike[str],
    *,
    status: str | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """List content-free records, oldest first, for approval UI discovery."""
    if status is not None and status not in STATUSES:
        raise ApprovalInputError("invalid approval status filter")
    current = _instant(now)

    def read(ledger: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
        records = [
            public_receipt(record)
            for record in ledger["requests"].values()
            if status is None or record["status"] == status
        ]
        records.sort(key=lambda record: (record["created_at"], record["approval_id"]))
        return records, False

    return _transaction(ledger_path, current, read)


def approve(
    ledger_path: str | os.PathLike[str],
    approval_id: str,
    *,
    human_identity: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Approve exactly one still-pending request as the named human."""
    current = _instant(now)
    requested_id = _identifier(approval_id, "approval_id")
    approver = _identifier(human_identity, "human_identity")

    def transition(ledger: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        record = ledger["requests"].get(requested_id)
        if record is None:
            raise ApprovalNotFound(f"approval {requested_id} does not exist")
        if record["status"] == "expired":
            raise ApprovalExpired(f"approval {requested_id} has expired")
        if record["status"] == "consumed":
            raise ApprovalReplay(f"approval {requested_id} was already consumed")
        if record["status"] != "pending":
            raise ApprovalStateError(f"approval {requested_id} is already {record['status']}")
        record["status"] = "approved"
        record["approved_at"] = _timestamp(current)
        record["approved_by"] = approver
        return public_receipt(record), True

    return _transaction(ledger_path, current, transition)


def consume(
    ledger_path: str | os.PathLike[str],
    approval_id: str,
    *,
    run_id: str,
    connector_id: str,
    tool_name: str,
    arguments: Mapping[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Consume one matching approval once and return a content-free receipt."""
    current = _instant(now)
    requested_id = _identifier(approval_id, "approval_id")
    expected = {
        "run_id": _identifier(run_id, "run_id"),
        "connector_id": _identifier(connector_id, "connector_id"),
        "tool_name": _identifier(tool_name, "tool_name"),
    }
    private_arguments = _private_arguments(arguments)
    argument_hash = canonical_arguments_sha256(private_arguments)

    def transition(ledger: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        record = ledger["requests"].get(requested_id)
        if record is None:
            raise ApprovalNotFound(f"approval {requested_id} does not exist")
        if record["status"] == "expired":
            raise ApprovalExpired(f"approval {requested_id} has expired")
        if record["status"] == "consumed":
            raise ApprovalReplay(f"approval {requested_id} was already consumed")
        if record["status"] != "approved":
            raise ApprovalStateError(f"approval {requested_id} is not approved")

        mismatch = next(
            (field for field, value in expected.items() if record.get(field) != value),
            None,
        )
        if mismatch is not None:
            raise ApprovalMismatch(f"approval {requested_id} {mismatch} does not match")
        if not hmac.compare_digest(record["arguments_sha256"], argument_hash):
            raise ApprovalMismatch(f"approval {requested_id} argument hash does not match")
        if _canonical_json(record["arguments"]) != _canonical_json(private_arguments):
            raise ApprovalMismatch(f"approval {requested_id} arguments do not match")

        record["status"] = "consumed"
        record["consumed_at"] = _timestamp(current)
        return public_receipt(record), True

    return _transaction(ledger_path, current, transition)


__all__ = [
    "ApprovalError",
    "ApprovalExpired",
    "ApprovalInputError",
    "ApprovalLedgerCorrupt",
    "ApprovalLimitError",
    "ApprovalMismatch",
    "ApprovalNotFound",
    "ApprovalReplay",
    "ApprovalStateError",
    "approve",
    "canonical_arguments_sha256",
    "consume",
    "get_for_review",
    "list_public",
    "public_receipt",
    "request_approval",
]
