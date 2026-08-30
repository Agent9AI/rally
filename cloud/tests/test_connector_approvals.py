from __future__ import annotations

import json
import multiprocessing
import stat
from datetime import UTC, datetime, timedelta

import pytest

import connector_approvals as approvals

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


def _new_request(path, *, ttl_seconds=300):
    return approvals.request_approval(
        path,
        run_id="r-approval-test",
        connector_id="hyperagent",
        tool_name="create_thread",
        arguments={"agentId": "agent-1", "message": "Prepare the launch brief"},
        ttl_seconds=ttl_seconds,
        now=NOW,
    )


def _consume_in_process(path, approval_id, barrier, output):
    barrier.wait()
    try:
        result = approvals.consume(
            path,
            approval_id,
            run_id="r-approval-test",
            connector_id="hyperagent",
            tool_name="create_thread",
            arguments={"message": "Prepare the launch brief", "agentId": "agent-1"},
            now=NOW + timedelta(seconds=2),
        )
        output.put(result["status"])
    except approvals.ApprovalReplay:
        output.put("replay")


def test_pending_request_keeps_exact_arguments_private_and_returns_public_receipt(tmp_path):
    ledger_path = tmp_path / "approvals.json"
    receipt = _new_request(ledger_path)

    assert receipt["status"] == "pending"
    assert receipt["arguments_sha256"] == approvals.canonical_arguments_sha256(
        {"message": "Prepare the launch brief", "agentId": "agent-1"}
    )
    assert "arguments" not in receipt

    review = approvals.get_for_review(ledger_path, receipt["approval_id"], now=NOW)
    assert review["arguments"] == {
        "agentId": "agent-1",
        "message": "Prepare the launch brief",
    }
    assert receipt["arguments_sha256"] == review["arguments_sha256"]
    assert "Prepare the launch brief" not in json.dumps(approvals.public_receipt(review))


def test_approve_and_consume_exact_request_once(tmp_path):
    ledger_path = tmp_path / "approvals.json"
    pending = _new_request(ledger_path)
    approved = approvals.approve(
        ledger_path,
        pending["approval_id"],
        human_identity="terry@ssecasolution.com",
        now=NOW + timedelta(seconds=1),
    )
    assert approved["status"] == "approved"
    assert approved["approved_by"] == "terry@ssecasolution.com"

    consumed = approvals.consume(
        ledger_path,
        pending["approval_id"],
        run_id="r-approval-test",
        connector_id="hyperagent",
        tool_name="create_thread",
        # Key order does not change the canonical argument binding.
        arguments={"message": "Prepare the launch brief", "agentId": "agent-1"},
        now=NOW + timedelta(seconds=2),
    )
    assert consumed["status"] == "consumed"
    assert "arguments" not in consumed

    with pytest.raises(approvals.ApprovalReplay):
        approvals.consume(
            ledger_path,
            pending["approval_id"],
            run_id="r-approval-test",
            connector_id="hyperagent",
            tool_name="create_thread",
            arguments={"agentId": "agent-1", "message": "Prepare the launch brief"},
            now=NOW + timedelta(seconds=3),
        )


@pytest.mark.parametrize(
    ("override", "match"),
    [
        ({"run_id": "r-other"}, "run_id"),
        ({"connector_id": "atlassian"}, "connector_id"),
        ({"tool_name": "send_message"}, "tool_name"),
        (
            {"arguments": {"agentId": "agent-1", "message": "Different request"}},
            "argument hash",
        ),
    ],
)
def test_mismatch_never_consumes_approval(tmp_path, override, match):
    ledger_path = tmp_path / "approvals.json"
    pending = _new_request(ledger_path)
    approvals.approve(
        ledger_path,
        pending["approval_id"],
        human_identity="human-operator",
        now=NOW + timedelta(seconds=1),
    )
    values = {
        "run_id": "r-approval-test",
        "connector_id": "hyperagent",
        "tool_name": "create_thread",
        "arguments": {"agentId": "agent-1", "message": "Prepare the launch brief"},
    }
    values.update(override)

    with pytest.raises(approvals.ApprovalMismatch, match=match):
        approvals.consume(
            ledger_path,
            pending["approval_id"],
            **values,
            now=NOW + timedelta(seconds=2),
        )

    review = approvals.get_for_review(
        ledger_path, pending["approval_id"], now=NOW + timedelta(seconds=2)
    )
    assert review["status"] == "approved"


def test_unapproved_request_cannot_be_consumed(tmp_path):
    ledger_path = tmp_path / "approvals.json"
    pending = _new_request(ledger_path)
    with pytest.raises(approvals.ApprovalStateError, match="not approved"):
        approvals.consume(
            ledger_path,
            pending["approval_id"],
            run_id="r-approval-test",
            connector_id="hyperagent",
            tool_name="create_thread",
            arguments={"agentId": "agent-1", "message": "Prepare the launch brief"},
            now=NOW + timedelta(seconds=1),
        )


def test_expiry_is_persisted_and_blocks_approval_or_consumption(tmp_path):
    ledger_path = tmp_path / "approvals.json"
    pending = _new_request(ledger_path, ttl_seconds=5)

    with pytest.raises(approvals.ApprovalExpired):
        approvals.approve(
            ledger_path,
            pending["approval_id"],
            human_identity="human-operator",
            now=NOW + timedelta(seconds=5),
        )
    expired = approvals.get_for_review(
        ledger_path, pending["approval_id"], now=NOW + timedelta(seconds=6)
    )
    assert expired["status"] == "expired"
    assert expired["expired_at"] == "2026-08-30T12:00:05.000000Z"

    pending_two = _new_request(ledger_path, ttl_seconds=5)
    approvals.approve(
        ledger_path,
        pending_two["approval_id"],
        human_identity="human-operator",
        now=NOW + timedelta(seconds=1),
    )
    with pytest.raises(approvals.ApprovalExpired):
        approvals.consume(
            ledger_path,
            pending_two["approval_id"],
            run_id="r-approval-test",
            connector_id="hyperagent",
            tool_name="create_thread",
            arguments={"agentId": "agent-1", "message": "Prepare the launch brief"},
            now=NOW + timedelta(seconds=5),
        )


def test_ledger_and_process_lock_are_private_files(tmp_path):
    ledger_path = tmp_path / "approvals.json"
    _new_request(ledger_path)
    lock_path = ledger_path.with_name(ledger_path.name + ".lock")

    assert stat.S_IMODE(ledger_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600
    assert not list(tmp_path.glob("*.tmp"))

    ledger_path.chmod(0o644)
    lock_path.chmod(0o644)
    approvals.list_public(ledger_path, now=NOW)
    assert stat.S_IMODE(ledger_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600


def test_process_lock_allows_only_one_concurrent_consumer(tmp_path):
    ledger_path = tmp_path / "approvals.json"
    pending = _new_request(ledger_path)
    approvals.approve(
        ledger_path,
        pending["approval_id"],
        human_identity="human-operator",
        now=NOW + timedelta(seconds=1),
    )

    context = multiprocessing.get_context("fork")
    barrier = context.Barrier(2)
    output = context.Queue()
    workers = [
        context.Process(
            target=_consume_in_process,
            args=(str(ledger_path), pending["approval_id"], barrier, output),
        )
        for _ in range(2)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)
        assert worker.exitcode == 0

    assert sorted(output.get(timeout=2) for _ in workers) == ["consumed", "replay"]


def test_bounded_ledger_prunes_terminal_records_but_never_active_ones(tmp_path, monkeypatch):
    ledger_path = tmp_path / "approvals.json"
    monkeypatch.setattr(approvals, "MAX_RECORDS", 2)
    first = _new_request(ledger_path)
    approvals.approve(
        ledger_path,
        first["approval_id"],
        human_identity="human-operator",
        now=NOW + timedelta(seconds=1),
    )
    approvals.consume(
        ledger_path,
        first["approval_id"],
        run_id="r-approval-test",
        connector_id="hyperagent",
        tool_name="create_thread",
        arguments={"agentId": "agent-1", "message": "Prepare the launch brief"},
        now=NOW + timedelta(seconds=2),
    )
    second = approvals.request_approval(
        ledger_path,
        run_id="r-second",
        connector_id="atlassian",
        tool_name="createJiraIssue",
        arguments={"summary": "One"},
        now=NOW + timedelta(seconds=3),
    )
    third = approvals.request_approval(
        ledger_path,
        run_id="r-third",
        connector_id="salesforce",
        tool_name="updateSobjectRecord",
        arguments={"id": "001", "body": {"Name": "Acme"}},
        now=NOW + timedelta(seconds=4),
    )

    assert [item["approval_id"] for item in approvals.list_public(ledger_path, now=NOW)] == [
        second["approval_id"],
        third["approval_id"],
    ]
    with pytest.raises(approvals.ApprovalLimitError):
        approvals.request_approval(
            ledger_path,
            run_id="r-fourth",
            connector_id="hyperagent",
            tool_name="send_message",
            arguments={"message": "No room"},
            now=NOW + timedelta(seconds=5),
        )


def test_rejects_non_json_and_oversized_or_invalid_ttl(tmp_path, monkeypatch):
    ledger_path = tmp_path / "approvals.json"
    with pytest.raises(approvals.ApprovalInputError, match="finite JSON"):
        approvals.request_approval(
            ledger_path,
            run_id="r-test",
            connector_id="hyperagent",
            tool_name="create_thread",
            arguments={"bad": float("nan")},
            now=NOW,
        )

    monkeypatch.setattr(approvals, "MAX_ARGUMENT_BYTES", 8)
    with pytest.raises(approvals.ApprovalInputError, match="byte approval limit"):
        approvals.request_approval(
            ledger_path,
            run_id="r-test",
            connector_id="hyperagent",
            tool_name="create_thread",
            arguments={"message": "too long"},
            now=NOW,
        )
    with pytest.raises(approvals.ApprovalInputError, match="TTL"):
        _new_request(ledger_path, ttl_seconds=0)
