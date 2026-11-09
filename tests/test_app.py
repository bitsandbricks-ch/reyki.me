import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
import app


def ing(name, host=None, ann=None, tls_host=None):
    spec = {}
    if host:
        spec["rules"] = [{"host": host}]
    if tls_host:
        spec["tls"] = [{"hosts": [tls_host]}]
    return {"metadata": {"name": name, "annotations": ann or {}}, "spec": spec}


class Entries(unittest.TestCase):
    def test_ingress_host_becomes_https_link(self):
        e = app.to_entry("Ingress", ing("grafana", "grafana.example.org"))
        self.assertEqual(e["url"], "https://grafana.example.org")
        self.assertEqual(e["name"], "grafana")

    def test_annotations_win(self):
        e = app.to_entry("Ingress", ing("x", "x.example.org", {
            "reyki.me/name": "Grafana", "reyki.me/description": "Dashboards",
            "reyki.me/group": "Monitoring", "reyki.me/url": "https://g.example.org/login", "reyki.me/order": "5"}))
        self.assertEqual((e["name"], e["description"], e["group"], e["url"], e["order"]),
                         ("Grafana", "Dashboards", "Monitoring", "https://g.example.org/login", 5))

    def test_httproute_hostnames(self):
        r = {"metadata": {"name": "git"}, "spec": {"hostnames": ["git.example.org"]}}
        self.assertEqual(app.to_entry("HTTPRoute", r)["url"], "https://git.example.org")

    def test_tls_host_fallback_and_skips(self):
        self.assertEqual(app.to_entry("Ingress", ing("a", tls_host="a.example.org"))["url"], "https://a.example.org")
        self.assertIsNone(app.to_entry("Ingress", ing("b")))
        self.assertIsNone(app.to_entry("Ingress", ing("c", "*.example.org")))
        self.assertIsNone(app.to_entry("Ingress", ing("d", "d.example.org", {"reyki.me/url": "javascript:alert(1)"})))

    def test_bad_order_falls_back(self):
        self.assertEqual(app.to_entry("Ingress", ing("a", "a.example.org", {"reyki.me/order": "x"}))["order"], 100)

    def test_build_sorts_and_dedupes(self):
        items = [("Ingress", [ing("b", "b.example.org", {"reyki.me/group": "Z"}), ing("a", "a.example.org"),
                              ing("c", "c.example.org", {"reyki.me/group": "Z", "reyki.me/order": "1"})]),
                 ("HTTPRoute", [{"metadata": {"name": "dup"}, "spec": {"hostnames": ["a.example.org"]}}])]
        self.assertEqual([e["name"] for e in app.build(items)], ["a", "c", "b"])


class Render(unittest.TestCase):
    def test_empty_renders_nothing(self):
        self.assertEqual(app.render([]), "")

    def test_escapes_and_groups(self):
        out = app.render([{"name": "<b>x</b>", "description": "a & b", "group": "G\"", "url": "https://x.example.org/?a=1&b=2"}])
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", out)
        self.assertIn("a &amp; b", out)
        self.assertIn("G&quot;", out)
        self.assertIn('href="https://x.example.org/?a=1&amp;b=2"', out)
        self.assertNotIn("<b>x</b>", out)

    def test_led_only_for_known_status(self):
        base = {"name": "n", "description": "", "group": "", "url": "https://n.example.org"}
        self.assertIn('class="led up"', app.render([dict(base, status="up")]))
        self.assertNotIn("class=\"led", app.render([base]))
        self.assertNotIn("class=\"led", app.render([dict(base, status="<x>")]))


if __name__ == "__main__":
    unittest.main()
