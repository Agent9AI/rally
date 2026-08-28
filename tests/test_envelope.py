"""The rules that make Rally more than prompting. If these fail, nothing else matters."""
import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import envelope as E


def item(iid="c1", state="open", owner=None, rejections=0):
    return {"id": iid, "description": "d", "state": state, "owner": owner,
            "verified_by": None, "evidence": None, "rejections": rejections}


class TestVerificationInvariant(unittest.TestCase):
    def test_owner_cannot_verify_own_work(self):
        prev = [item(state="awaiting-verification", owner="claude")]
        proposed = [item(state="done", owner="claude")]
        out, viol = E.reconcile(prev, proposed, actor="claude")
        self.assertEqual(out[0]["state"], "awaiting-verification", "self-verification must be reverted")
        self.assertTrue(any("cannot verify its own work" in v for v in viol))

    def test_other_agent_may_verify(self):
        prev = [item(state="awaiting-verification", owner="claude")]
        proposed = [item(state="done", owner="claude")]
        out, viol = E.reconcile(prev, proposed, actor="agy")
        self.assertEqual(out[0]["state"], "done")
        self.assertEqual(out[0]["verified_by"], "agy")
        self.assertEqual(viol, [])

    def test_done_requires_awaiting_verification(self):
        prev = [item(state="claimed", owner="claude")]
        proposed = [item(state="done", owner="claude")]
        out, viol = E.reconcile(prev, proposed, actor="agy")
        self.assertEqual(out[0]["state"], "claimed")
        self.assertTrue(any("requires awaiting-verification" in v for v in viol))


class TestRejectionBound(unittest.TestCase):
    def test_rejection_increments(self):
        prev = [item(state="awaiting-verification", owner="claude", rejections=0)]
        proposed = [item(state="claimed", owner="claude")]
        out, _ = E.reconcile(prev, proposed, actor="agy")
        self.assertEqual(out[0]["state"], "claimed")
        self.assertEqual(out[0]["rejections"], 1)

    def test_third_rejection_disputes(self):
        prev = [item(state="awaiting-verification", owner="claude", rejections=2)]
        proposed = [item(state="claimed", owner="claude")]
        out, _ = E.reconcile(prev, proposed, actor="agy", rejections_max=2)
        self.assertEqual(out[0]["state"], "disputed", "the bound must terminate the loop")

    def test_owner_cannot_reject_own_item(self):
        prev = [item(state="awaiting-verification", owner="claude")]
        proposed = [item(state="claimed", owner="claude")]
        out, viol = E.reconcile(prev, proposed, actor="claude")
        self.assertEqual(out[0]["state"], "awaiting-verification")
        self.assertTrue(any("cannot reject your own" in v for v in viol))


class TestChecklistIntegrity(unittest.TestCase):
    def test_dropped_items_are_restored(self):
        prev = [item("c1"), item("c2")]
        out, viol = E.reconcile(prev, [item("c1")], actor="claude")
        self.assertEqual({i["id"] for i in out}, {"c1", "c2"})
        self.assertTrue(any("dropped" in v for v in viol))

    def test_new_items_allowed_during_negotiation(self):
        out, viol = E.reconcile([item("c1")], [item("c1"), item("c2")], actor="agy")
        self.assertEqual({i["id"] for i in out}, {"c1", "c2"})
        self.assertEqual(viol, [])

    def test_new_item_cannot_start_done(self):
        out, viol = E.reconcile([], [item("c9", state="done")], actor="agy")
        self.assertEqual(out[0]["state"], "open")
        self.assertTrue(viol)

    def test_advance_requires_ownership(self):
        prev = [item(state="claimed", owner="claude")]
        proposed = [item(state="awaiting-verification", owner="claude")]
        out, viol = E.reconcile(prev, proposed, actor="agy")
        self.assertEqual(out[0]["state"], "claimed")
        self.assertTrue(any("may not advance" in v for v in viol))


class TestExtraction(unittest.TestCase):
    def test_last_fenced_block_wins(self):
        text = ('here is the format ```json {"checklist": [], "note": "example"} ```\n'
                'my answer:\n```json\n{"rally_version":1,"checklist":[{"id":"c1"}],"narrative":"x"}\n```')
        env = E.extract(text)
        self.assertEqual(env["checklist"][0]["id"], "c1")

    def test_bare_object(self):
        env = E.extract('{"rally_version":1,"checklist":[{"id":"z"}],"narrative":"x"}')
        self.assertEqual(env["checklist"][0]["id"], "z")

    def test_prose_only_returns_none(self):
        self.assertIsNone(E.extract("I finished the task, everything looks good."))


class TestCompletion(unittest.TestCase):
    def test_is_complete(self):
        self.assertTrue(E.is_complete([item(state="done"), item("c2", state="done")]))
        self.assertFalse(E.is_complete([item(state="done"), item("c2", state="claimed")]))
        self.assertFalse(E.is_complete([]))

    def test_digest_changes_with_progress(self):
        a = E.digest([item(state="open")])
        b = E.digest([item(state="claimed", owner="agy")])
        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestClaimAndWorkSameTurn(unittest.TestCase):
    """Regression: agy legitimately claimed and worked five items in one turn."""

    def test_open_to_awaiting_in_one_turn(self):
        out, viol = E.reconcile([item("c1")], [item("c1", state="awaiting-verification", owner="agy")],
                                actor="agy")
        self.assertEqual(out[0]["state"], "awaiting-verification")
        self.assertEqual(out[0]["owner"], "agy")
        self.assertEqual(viol, [])

    def test_open_to_done_still_illegal(self):
        out, viol = E.reconcile([item("c1")], [item("c1", state="done")], actor="agy")
        self.assertEqual(out[0]["state"], "open", "verification cannot be skipped")
        self.assertTrue(viol)


class TestScopeClosure(unittest.TestCase):
    """Regression: the first live run grew 5 items into 8 by inventing
    verification-of-verification items. Scope closes after negotiation."""

    def test_new_items_rejected_once_scope_closed(self):
        out, viol = E.reconcile([item("c1")], [item("c1"), item("c9")],
                                actor="agy", allow_new=False)
        self.assertEqual({i["id"] for i in out}, {"c1"})
        self.assertTrue(any("scope is closed" in v for v in viol))

    def test_new_items_allowed_while_open(self):
        out, viol = E.reconcile([item("c1")], [item("c1"), item("c9")],
                                actor="agy", allow_new=True)
        self.assertEqual({i["id"] for i in out}, {"c1", "c9"})
