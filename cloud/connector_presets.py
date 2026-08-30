"""Conservative, provider-verified tool-policy presets for Rally connectors."""

from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from typing import Any


class ConnectorPresetError(ValueError):
    """Raised when a connector preset cannot be constructed safely."""


ToolPolicy = dict[str, dict[str, Any]]

_READ_SMALL = {
    "risk": "read",
    "constraints": {"max_argument_bytes": 8 * 1024, "max_result_bytes": 64 * 1024},
}
_READ_STANDARD = {
    "risk": "read",
    "constraints": {"max_argument_bytes": 32 * 1024, "max_result_bytes": 256 * 1024},
}

_PRESETS: dict[tuple[str, str], ToolPolicy] = {
    ("google-workspace", "read-minimal"): {
        "gmail.list_drafts": deepcopy(_READ_SMALL),
        "gmail.get_draft": deepcopy(_READ_STANDARD),
        "gmail.get_thread": deepcopy(_READ_STANDARD),
        "gmail.get_message": deepcopy(_READ_STANDARD),
        "gmail.search_threads": deepcopy(_READ_STANDARD),
        "gmail.list_labels": deepcopy(_READ_SMALL),
        "drive.download_file_content": deepcopy(_READ_STANDARD),
        "drive.get_file_metadata": deepcopy(_READ_SMALL),
        "drive.get_file_permissions": deepcopy(_READ_SMALL),
        "drive.list_recent_files": deepcopy(_READ_STANDARD),
        "drive.read_file_content": deepcopy(_READ_STANDARD),
        "drive.search_files": deepcopy(_READ_STANDARD),
        "docs.read_doc": deepcopy(_READ_STANDARD),
        "sheets.get_values": deepcopy(_READ_STANDARD),
        "sheets.get_spreadsheet": deepcopy(_READ_STANDARD),
        "slides.read_presentation": deepcopy(_READ_STANDARD),
        "calendar.list_events": deepcopy(_READ_STANDARD),
        "calendar.get_event": deepcopy(_READ_SMALL),
        "calendar.list_calendars": deepcopy(_READ_SMALL),
        "calendar.suggest_time": deepcopy(_READ_SMALL),
        "calendar.search_events": deepcopy(_READ_STANDARD),
        "chat.list_messages": deepcopy(_READ_STANDARD),
        "chat.search_messages": deepcopy(_READ_STANDARD),
        "chat.search_conversations": deepcopy(_READ_STANDARD),
        "people.search_directory_people": deepcopy(_READ_STANDARD),
        "people.search_contacts": deepcopy(_READ_STANDARD),
        "people.get_user_profile": deepcopy(_READ_SMALL),
    },
    ("slack", "read-minimal"): {
        "slack_search_public": deepcopy(_READ_STANDARD),
        "slack_search_channels": deepcopy(_READ_STANDARD),
        "slack_search_users": deepcopy(_READ_STANDARD),
        "slack_read_channel": deepcopy(_READ_STANDARD),
        "slack_read_thread": deepcopy(_READ_STANDARD),
        "slack_read_file": deepcopy(_READ_STANDARD),
        "slack_read_user_profile": deepcopy(_READ_SMALL),
        "slack_list_channel_members": deepcopy(_READ_STANDARD),
    },
    ("github", "read-only"): {
        "get_me": deepcopy(_READ_SMALL),
        "get_file_contents": deepcopy(_READ_STANDARD),
        "list_branches": deepcopy(_READ_STANDARD),
        "list_commits": deepcopy(_READ_STANDARD),
        "list_releases": deepcopy(_READ_STANDARD),
        "list_tags": deepcopy(_READ_STANDARD),
        "issue_read": deepcopy(_READ_STANDARD),
        "pull_request_read": deepcopy(_READ_STANDARD),
        "search_code": deepcopy(_READ_STANDARD),
        "search_repositories": deepcopy(_READ_STANDARD),
    },
    ("salesforce", "sobject-reads"): {
        "getObjectSchema": {
            "risk": "read",
            "constraints": {
                "arguments": {"object-name": {"max_length": 255}},
                "max_argument_bytes": 8 * 1024,
                "max_result_bytes": 256 * 1024,
            },
        },
        "soqlQuery": {
            "risk": "read",
            "constraints": {
                "arguments": {"query": {"required": True, "max_length": 10_000}},
                "max_argument_bytes": 16 * 1024,
                "max_result_bytes": 256 * 1024,
            },
        },
        "find": {
            "risk": "read",
            "constraints": {
                "arguments": {"search": {"required": True, "max_length": 5_000}},
                "max_argument_bytes": 8 * 1024,
                "max_result_bytes": 256 * 1024,
            },
        },
        "getUserInfo": deepcopy(_READ_SMALL),
        "listRecentSobjectRecords": {
            "risk": "read",
            "constraints": {
                "arguments": {
                    "sobject-name": {"required": True, "max_length": 255}
                },
                "max_argument_bytes": 8 * 1024,
                "max_result_bytes": 256 * 1024,
            },
        },
        "getRelatedRecords": {
            "risk": "read",
            "constraints": {
                "arguments": {
                    "sobject-name": {"required": True, "max_length": 255},
                    "id": {"required": True, "max_length": 18},
                    "relationship-path": {"required": True, "max_length": 512},
                },
                "max_argument_bytes": 8 * 1024,
                "max_result_bytes": 256 * 1024,
            },
        },
    },
    ("cloudflare", "observability"): {
        "query_worker_observability": deepcopy(_READ_STANDARD),
        "observability_keys": deepcopy(_READ_SMALL),
        "observability_values": deepcopy(_READ_SMALL),
    },
    ("stripe", "read-minimal"): {
        "get_stripe_account_info": deepcopy(_READ_SMALL),
        "search_stripe_documentation": deepcopy(_READ_STANDARD),
        "stripe_api_search": deepcopy(_READ_SMALL),
        "stripe_api_details": deepcopy(_READ_SMALL),
    },
    ("bigquery", "metadata-only"): {
        "list_dataset_ids": {
            "risk": "read",
            "constraints": {
                "arguments": {"project_id": {"required": True, "max_length": 128}},
                "max_result_bytes": 128 * 1024,
            },
        },
        "get_dataset_info": {
            "risk": "read",
            "constraints": {
                "arguments": {
                    "project_id": {"required": True, "max_length": 128},
                    "dataset_id": {"required": True, "max_length": 1024},
                },
                "max_result_bytes": 128 * 1024,
            },
        },
        "list_table_ids": {
            "risk": "read",
            "constraints": {
                "arguments": {
                    "project_id": {"required": True, "max_length": 128},
                    "dataset_id": {"required": True, "max_length": 1024},
                },
                "max_result_bytes": 128 * 1024,
            },
        },
        "get_table_info": {
            "risk": "read",
            "constraints": {
                "arguments": {
                    "project_id": {"required": True, "max_length": 128},
                    "dataset_id": {"required": True, "max_length": 1024},
                    "table_id": {"required": True, "max_length": 1024},
                },
                "max_result_bytes": 256 * 1024,
            },
        },
    },
    ("n8n", "workflow-bounded"): {
        "get_workflow_details": {
            "risk": "read",
            "constraints": {
                "arguments": {
                    "workflowId": {"required": True, "allowed_values": []},
                    "detailLevel": {
                        "required": True,
                        "allowed_values": ["execution"],
                    },
                },
                "max_argument_bytes": 32 * 1024,
                "max_result_bytes": 256 * 1024,
            },
        },
        "execute_workflow": {
            "risk": "human_approval",
            "constraints": {
                "arguments": {
                    "workflowId": {"required": True, "allowed_values": []},
                    "executionMode": {
                        "required": True,
                        "allowed_values": ["production"],
                    },
                },
                "max_argument_bytes": 64 * 1024,
                "max_result_bytes": 32 * 1024,
            },
        },
    },
    ("atlassian", "read-minimal"): {
        "atlassianUserInfo": deepcopy(_READ_SMALL),
        "getAccessibleAtlassianResources": deepcopy(_READ_SMALL),
        "search": {
            "risk": "read",
            "constraints": {
                "arguments": {"query": {"required": True, "max_length": 2000}},
                "max_argument_bytes": 16 * 1024,
                "max_result_bytes": 256 * 1024,
            },
        },
        "fetch": {
            "risk": "read",
            "constraints": {
                "arguments": {"id": {"required": True, "max_length": 512}},
                "max_argument_bytes": 16 * 1024,
                "max_result_bytes": 256 * 1024,
            },
        },
    },
    ("hyperagent", "read-minimal"): {
        "list_agents": deepcopy(_READ_SMALL),
        "list_threads": deepcopy(_READ_STANDARD),
        "get_thread": {
            "risk": "read",
            "constraints": {
                "arguments": {"threadId": {"required": True, "max_length": 256}},
                "max_argument_bytes": 16 * 1024,
                "max_result_bytes": 256 * 1024,
            },
        },
        "list_pending_approvals": deepcopy(_READ_STANDARD),
    },
}

_KNOWN_CONNECTORS = frozenset(connector for connector, _ in _PRESETS)


def _workflow_ids(values: Iterable[str] | None) -> list[str]:
    if values is None or isinstance(values, (str, bytes)):
        raise ConnectorPresetError(
            "n8n workflow-bounded requires one or more allowed workflow IDs"
        )
    materialized = list(values)
    if any(not isinstance(value, str) for value in materialized):
        raise ConnectorPresetError("n8n workflow IDs must be strings")
    normalized = sorted({value.strip() for value in materialized})
    if not normalized or any(not value for value in normalized):
        raise ConnectorPresetError(
            "n8n workflow-bounded requires one or more non-empty workflow IDs"
        )
    return normalized


def build_connector_preset(
    connector_id: str,
    preset_name: str,
    *,
    allowed_workflow_ids: Iterable[str] | None = None,
) -> ToolPolicy:
    """Return an independent Rally tool-policy mapping for one named preset.

    Built-in policies are never returned directly. Callers may safely customize
    the resulting mapping without changing subsequent preset construction.
    """
    if connector_id not in _KNOWN_CONNECTORS:
        raise ConnectorPresetError(f"unknown connector: {connector_id}")
    key = (connector_id, preset_name)
    if key not in _PRESETS:
        raise ConnectorPresetError(
            f"unknown preset for {connector_id}: {preset_name}"
        )

    policy = deepcopy(_PRESETS[key])
    if key == ("n8n", "workflow-bounded"):
        workflow_ids = _workflow_ids(allowed_workflow_ids)
        for rule in policy.values():
            rule["constraints"]["arguments"]["workflowId"]["allowed_values"] = list(
                workflow_ids
            )
    return policy
