import json
import os
import re
import unittest
from html.parser import HTMLParser


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")


class LinkCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag in {"a", "link"} and values.get("href"):
            self.links.append(values["href"])
        if tag in {"img", "script"} and values.get("src"):
            self.links.append(values["src"])


class TestProductSite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(SITE, "index.html")) as handle:
            cls.html = handle.read()

    def test_event_copy_is_current_and_stale_event_is_absent(self):
        self.assertIn("All Things Agentic Hackathon", self.html)
        self.assertNotIn("dev" + "fest", self.html.lower())

    def test_product_proof_and_honest_boundary_are_visible(self):
        for phrase in (
            "Your AIs, finally",
            "The accountable AI team",
            "Your AIs can solve the problem",
            "shared operating system for communication, delegation, and execution",
            "One hard goal",
            "Watch the accountable team work",
            "No model approves its own work",
            "OpenAI Codex",
            "Connections remain per user",
            "Approved systems",
            "Scoped for this run",
            "Are AI and business-system connections shared between users?",
            "Second Wind recovery",
            "Bounded recovery, not auto-approval",
            "Gemini 3.7 + ADK",
            "Rally runs one model at a time",
            "The authoritative runner dispatches the next model locally",
            "The handshake now speaks a standard",
            "Google introduced the Agent2Agent (A2A) Protocol",
            "introduced by Google",
            "Rally publishes an A2A v1.0 Agent Card",
            "Accepted into AAIF at Growth Stage",
            "A2A v1.0 compatible",
            "Agent discovery + task exchange",
            "Originally created by",
            "Linux Foundation open governance",
            "WebMCP enabled",
            "3 browser tools · human-confirmed",
            "exposes three user-present browser tools without autonomous submission",
            "Can a browser agent use Rally directly?",
            "three WebMCP tools",
            "it cannot submit the job",
        ):
            self.assertIn(phrase, self.html)
        self.assertIn('src="rally-symbol.png"', self.html)
        self.assertIn('src="rally-logo.png"', self.html)
        self.assertIn('src="a2a-icon.svg"', self.html)
        self.assertIn('class="a2a-trust"', self.html)
        self.assertIn('class="webmcp-trust-badge"', self.html)
        self.assertNotIn('class="webmcp-cta"', self.html)
        self.assertIn('class="access-ring"', self.html)
        self.assertIn('data-layer="approved-systems"', self.html)
        self.assertEqual(self.html.count('data-layer="agent-workforce"'), 3)
        self.assertNotIn('class="mission-assets"', self.html)
        self.assertIn("Agent <i>→</i> Rally <i>→</i> Agent", self.html)
        self.assertIn("One governed handoff moves sequentially", self.html)
        self.assertEqual(self.html.count('class="story-kicker"'), 3)
        self.assertEqual(self.html.count('class="feature-kicker"'), 3)
        self.assertIn("handoff accepted", self.html)
        self.assertIn("routing next turn", self.html)
        for provider, worker in (("Google", "Gemini"), ("Anthropic", "Claude"), ("OpenAI", "Codex")):
            self.assertIn(f"<small>{provider}</small><strong>{worker}</strong>", self.html)
        for agent_mark in ("antigravity.png", "claude.svg", "openai.svg"):
            self.assertIn(f'src="brandmarks/{agent_mark}"', self.html)
            path = os.path.join(SITE, "brandmarks", agent_mark)
            self.assertTrue(os.path.exists(path))
            self.assertGreater(os.path.getsize(path), 500)
        for placeholder in (
            '<span class="model-avatar">G</span>',
            '<span class="model-avatar">C</span>',
            '<span class="model-avatar">O</span>',
        ):
            self.assertNotIn(placeholder, self.html)
        self.assertNotIn('class="mission-context"', self.html)
        self.assertNotIn('class="connector-boundary"', self.html)
        self.assertNotIn("Explore the source", self.html)
        self.assertNotIn("View source", self.html)
        self.assertEqual(self.html.count('class="flow-kicker"'), 4)
        for phase in ("Commission", "Govern", "Execute", "Prove"):
            self.assertIn(f'<p class="label">{phase}</p>', self.html)
        self.assertIn('name="rally-console-api"', self.html)
        self.assertIn('content="https://rally.agent9.dev/v1/console"', self.html)
        self.assertIn('rel="canonical" href="https://rally.agent9.dev/"', self.html)
        self.assertIn("data-second-wind", self.html)
        self.assertIn("Loading authoritative runs", self.html)
        for connector in (
            "Google Workspace", "Slack", "GitHub", "Cloudflare", "n8n", "Stripe",
            "BigQuery", "Atlassian", "Salesforce",
        ):
            self.assertIn(f'data-connector="{connector}"', self.html)
        for agent_connector in ("Hyperagent", "Hermes Agent", "OpenClaw"):
            self.assertIn(f'data-agent-connection="{agent_connector}"', self.html)
        self.assertNotIn("Prime Intellect", self.html)
        self.assertNotIn("Where is Prime Intellect?", self.html)
        self.assertNotIn('class="execution-note"', self.html)
        for brand_asset in (
            "google.svg", "slack.svg", "github.svg", "cloudflare.svg", "n8n.svg",
            "stripe.svg", "bigquery.svg", "atlassian.svg", "salesforce.svg",
            "hyperagent.svg", "openclaw.svg",
        ):
            path = os.path.join(SITE, "brandmarks", brand_asset)
            self.assertTrue(os.path.exists(path))
            self.assertGreater(os.path.getsize(path), 500)
        self.assertNotIn("Request a managed pilot", self.html)
        self.assertNotIn("Webhook launch", self.html)
        for logo_asset in ("rally-logo.png", "rally-symbol.png"):
            path = os.path.join(SITE, logo_asset)
            self.assertTrue(os.path.exists(path))
            self.assertGreater(os.path.getsize(path), 10_000)
        with open(os.path.join(SITE, "styles.css")) as handle:
            styles = handle.read()
        self.assertIn("rally-handoff", styles)
        self.assertIn("mission-control-rotate", styles)
        self.assertIn('class="governance-marker"', self.html)
        self.assertIn("mission-governance-marker", styles)
        self.assertIn("prefers-reduced-motion", styles)
        with open(os.path.join(SITE, ".well-known", "agent-card.json")) as handle:
            agent_card = json.load(handle)
        self.assertEqual(agent_card["version"], "1.0.0")
        self.assertEqual(
            [entry["protocolBinding"] for entry in agent_card["supportedInterfaces"]],
            ["JSONRPC", "HTTP+JSON"],
        )
        self.assertEqual(
            [skill["id"] for skill in agent_card["skills"]],
            ["commission_governed_run"],
        )
        self.assertNotIn("test-token", str(agent_card))
        with open(os.path.join(SITE, "app.js")) as handle:
            app = handle.read()
        self.assertIn("Second Wind recovery:", app)
        self.assertIn('entry.kind === "recovery"', app)
        self.assertIn("document.modelContext.registerTool({", app)
        for tool in (
            "rally_list_public_runs",
            "rally_inspect_public_run",
            "rally_draft_job",
        ):
            self.assertIn(f'name: "{tool}"', app)
        self.assertIn('status: "drafted_not_submitted"', app)
        self.assertIn("human_confirmation_required: true", app)
        self.assertIn("transmitted: false", app)
        self.assertIn("stored: false", app)
        self.assertIn("readOnlyHint: true, untrustedContentHint: true", app)
        self.assertIn("additionalProperties: false", app)
        self.assertIn("closedWebMcpInput", app)
        self.assertIn("maxLength: 2000", app)
        with open(os.path.join(ROOT, "studio", "og-card.html")) as handle:
            card = handle.read()
        for phrase in ("THE ACCOUNTABLE AI TEAM", "Your AIs, finally", "180", "6/6", "0"):
            self.assertIn(phrase, card)
        self.assertNotIn("99 TESTS", card)

    def test_local_assets_exist_and_no_dead_hash_links(self):
        parser = LinkCollector()
        parser.feed(self.html)
        for link in parser.links:
            self.assertNotEqual(link, "#")
            if re.match(r"^(?:https?:|mailto:|#)", link):
                continue
            target = link.split("?", 1)[0].split("#", 1)[0].lstrip("/")
            self.assertTrue(os.path.exists(os.path.join(SITE, target)), link)

    def test_static_site_has_security_headers(self):
        with open(os.path.join(SITE, "_headers")) as handle:
            headers = handle.read()
        self.assertIn("Content-Security-Policy", headers)
        self.assertIn("frame-ancestors 'none'", headers)
        self.assertIn("connect-src 'self' https://rally.agent9.dev", headers)
        self.assertIn("tools=(self)", headers)
        with open(os.path.join(ROOT, "src", "worker", "wrangler.jsonc")) as handle:
            worker_config = json.load(handle)
        self.assertEqual(
            worker_config["routes"],
            [{"pattern": "rally.agent9.dev", "custom_domain": True}],
        )
        self.assertTrue(worker_config["workers_dev"])
        self.assertFalse(worker_config["preview_urls"])
        with open(os.path.join(ROOT, "src", "worker", "index.js")) as handle:
            worker = handle.read()
        self.assertIn('const SITE_ORIGIN = "https://agent9-rally.pages.dev"', worker)
        self.assertIn("return await fetch(new Request(upstreamUrl, request))", worker)


if __name__ == "__main__":
    unittest.main()
