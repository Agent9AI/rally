import pytest

from connector_presets import ConnectorPresetError, build_connector_preset


def test_google_workspace_read_minimal_is_service_qualified_and_read_only():
    policy = build_connector_preset("google-workspace", "read-minimal")
    assert set(policy) == {
        "gmail.list_drafts",
        "gmail.get_draft",
        "gmail.get_thread",
        "gmail.get_message",
        "gmail.search_threads",
        "gmail.list_labels",
        "drive.download_file_content",
        "drive.get_file_metadata",
        "drive.get_file_permissions",
        "drive.list_recent_files",
        "drive.read_file_content",
        "drive.search_files",
        "docs.read_doc",
        "sheets.get_values",
        "sheets.get_spreadsheet",
        "slides.read_presentation",
        "calendar.list_events",
        "calendar.get_event",
        "calendar.list_calendars",
        "calendar.suggest_time",
        "calendar.search_events",
        "chat.list_messages",
        "chat.search_messages",
        "chat.search_conversations",
        "people.search_directory_people",
        "people.search_contacts",
        "people.get_user_profile",
    }
    assert all("." in tool_name for tool_name in policy)
    assert "gmail.create_draft" not in policy
    assert "gmail.send_message" not in policy
    assert "drive.create_file" not in policy
    assert {rule["risk"] for rule in policy.values()} == {"read"}


def test_slack_read_minimal_excludes_private_search_and_mutations():
    policy = build_connector_preset("slack", "read-minimal")
    assert set(policy) == {
        "slack_search_public",
        "slack_search_channels",
        "slack_search_users",
        "slack_read_channel",
        "slack_read_thread",
        "slack_read_file",
        "slack_read_user_profile",
        "slack_list_channel_members",
    }
    assert "slack_search_public_and_private" not in policy
    assert "slack_send_message" not in policy
    assert "slack_create_channel" not in policy
    assert {rule["risk"] for rule in policy.values()} == {"read"}


def test_github_read_only_matches_server_enforced_read_surface():
    policy = build_connector_preset("github", "read-only")
    assert set(policy) == {
        "get_me",
        "get_file_contents",
        "list_branches",
        "list_commits",
        "list_releases",
        "list_tags",
        "issue_read",
        "pull_request_read",
        "search_code",
        "search_repositories",
    }
    assert "create_or_update_file" not in policy
    assert "issue_write" not in policy
    assert "merge_pull_request" not in policy
    assert {rule["risk"] for rule in policy.values()} == {"read"}


def test_salesforce_sobject_reads_uses_exact_bounded_provider_tools():
    policy = build_connector_preset("salesforce", "sobject-reads")
    assert set(policy) == {
        "getObjectSchema",
        "soqlQuery",
        "find",
        "getUserInfo",
        "listRecentSobjectRecords",
        "getRelatedRecords",
    }
    assert policy["soqlQuery"]["constraints"]["arguments"]["query"] == {
        "required": True,
        "max_length": 10_000,
    }
    assert policy["find"]["constraints"]["arguments"]["search"] == {
        "required": True,
        "max_length": 5_000,
    }
    assert "createSobjectRecord" not in policy
    assert "updateSobjectRecord" not in policy
    assert "deleteSobjectRecord" not in policy
    assert {rule["risk"] for rule in policy.values()} == {"read"}


def test_cloudflare_observability_is_exact_and_read_only():
    policy = build_connector_preset("cloudflare", "observability")
    assert set(policy) == {
        "query_worker_observability",
        "observability_keys",
        "observability_values",
    }
    assert {rule["risk"] for rule in policy.values()} == {"read"}


def test_stripe_read_minimal_excludes_broad_reads_and_writes():
    policy = build_connector_preset("stripe", "read-minimal")
    assert set(policy) == {
        "get_stripe_account_info",
        "search_stripe_documentation",
        "stripe_api_search",
        "stripe_api_details",
    }
    assert "stripe_api_read" not in policy
    assert "stripe_api_write" not in policy
    assert "create_refund" not in policy
    assert {rule["risk"] for rule in policy.values()} == {"read"}


def test_bigquery_metadata_only_has_no_query_surface():
    policy = build_connector_preset("bigquery", "metadata-only")
    assert set(policy) == {
        "list_dataset_ids",
        "get_dataset_info",
        "list_table_ids",
        "get_table_info",
    }
    assert "execute_sql" not in policy
    assert "execute_sql_readonly" not in policy
    assert policy["get_table_info"]["constraints"]["arguments"]["table_id"] == {
        "required": True,
        "max_length": 1024,
    }


def test_n8n_template_requires_and_freezes_allowed_workflow_ids():
    requested = ["wf-z", " wf-a ", "wf-z"]
    policy = build_connector_preset(
        "n8n", "workflow-bounded", allowed_workflow_ids=requested
    )
    requested.append("wf-late")

    for rule in policy.values():
        assert rule["constraints"]["arguments"]["workflowId"]["allowed_values"] == [
            "wf-a",
            "wf-z",
        ]
    assert policy["get_workflow_details"]["risk"] == "read"
    assert policy["execute_workflow"]["risk"] == "human_approval"
    assert policy["execute_workflow"]["constraints"]["arguments"]["executionMode"] == {
        "required": True,
        "allowed_values": ["production"],
    }


@pytest.mark.parametrize("workflow_ids", [None, [], (), [""], ["  "]])
def test_n8n_template_rejects_empty_required_resources(workflow_ids):
    with pytest.raises(ConnectorPresetError, match="workflow IDs"):
        build_connector_preset(
            "n8n", "workflow-bounded", allowed_workflow_ids=workflow_ids
        )


@pytest.mark.parametrize("workflow_ids", [[123], ["wf-approved", None]])
def test_n8n_template_rejects_non_string_resources(workflow_ids):
    with pytest.raises(ConnectorPresetError, match="must be strings"):
        build_connector_preset(
            "n8n", "workflow-bounded", allowed_workflow_ids=workflow_ids
        )


def test_atlassian_read_minimal_uses_provider_search_and_fetch():
    policy = build_connector_preset("atlassian", "read-minimal")
    assert set(policy) == {
        "atlassianUserInfo",
        "getAccessibleAtlassianResources",
        "search",
        "fetch",
    }
    assert policy["search"]["constraints"]["arguments"]["query"]["required"] is True
    assert {rule["risk"] for rule in policy.values()} == {"read"}


def test_hyperagent_read_minimal_includes_pending_approvals_but_not_resolution():
    policy = build_connector_preset("hyperagent", "read-minimal")
    assert set(policy) == {
        "list_agents",
        "list_threads",
        "get_thread",
        "list_pending_approvals",
    }
    assert "resolve_approval" not in policy
    assert "create_thread" not in policy
    assert {rule["risk"] for rule in policy.values()} == {"read"}


def test_presets_are_deep_copied_between_calls():
    first = build_connector_preset("stripe", "read-minimal")
    first["stripe_api_search"]["constraints"]["max_result_bytes"] = 1
    first["invented_write"] = {"risk": "read"}

    second = build_connector_preset("stripe", "read-minimal")
    assert second["stripe_api_search"]["constraints"]["max_result_bytes"] == 64 * 1024
    assert "invented_write" not in second


@pytest.mark.parametrize(
    ("connector_id", "preset_name", "message"),
    [
        ("unknown", "read-minimal", "unknown connector"),
        ("stripe", "metadata-only", "unknown preset"),
    ],
)
def test_unknown_connector_and_preset_are_rejected(connector_id, preset_name, message):
    with pytest.raises(ConnectorPresetError, match=message):
        build_connector_preset(connector_id, preset_name)


def test_every_rule_has_only_supported_shape_and_no_ungated_write():
    cases = [
        ("google-workspace", "read-minimal", None),
        ("slack", "read-minimal", None),
        ("github", "read-only", None),
        ("salesforce", "sobject-reads", None),
        ("cloudflare", "observability", None),
        ("stripe", "read-minimal", None),
        ("bigquery", "metadata-only", None),
        ("n8n", "workflow-bounded", ["wf-approved"]),
        ("atlassian", "read-minimal", None),
        ("hyperagent", "read-minimal", None),
    ]
    for connector_id, preset_name, workflow_ids in cases:
        policy = build_connector_preset(
            connector_id,
            preset_name,
            allowed_workflow_ids=workflow_ids,
        )
        for rule in policy.values():
            assert set(rule) <= {"risk", "constraints"}
            assert rule["risk"] in {"read", "human_approval"}
            if rule["risk"] == "human_approval":
                assert connector_id == "n8n"
