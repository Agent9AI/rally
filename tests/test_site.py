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
            "Zero self-approval",
            "Gemini 3.7 + ADK",
            "No API keys",
            "The authoritative runner dispatches the next model locally",
        ):
            self.assertIn(phrase, self.html)

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
        self.assertIn("connect-src 'none'", headers)


if __name__ == "__main__":
    unittest.main()
