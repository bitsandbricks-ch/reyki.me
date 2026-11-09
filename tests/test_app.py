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
        self.assertEqual((e["url"], e["name"], e["probe"]), ("https://grafana.example.org", "grafana", "https://grafana.example.org"))

    def test_annotations_win(self):
        e = app.to_entry("Ingress", ing("x", "x.example.org", {
            "reyki.me/name": "Grafana", "reyki.me/description": "Dashboards", "reyki.me/group": "Monitoring",
            "reyki.me/url": "https://g.example.org/login", "reyki.me/order": "5",
            "reyki.me/probe-url": "http://grafana.monitoring.svc:3000/api/health"}))
        self.assertEqual((e["name"], e["description"], e["group"], e["url"], e["order"], e["probe"]),
                         ("Grafana", "Dashboards", "Monitoring", "https://g.example.org/login", 5,
                          "http://grafana.monitoring.svc:3000/api/health"))

    def test_probe_off_or_bad(self):
        self.assertIsNone(app.to_entry("Ingress", ing("a", "a.example.org", {"reyki.me/probe": "false"}))["probe"])
        self.assertIsNone(app.to_entry("Ingress", ing("a", "a.example.org", {"reyki.me/probe-url": "file:///etc/passwd"}))["probe"])

    def test_httproute_hostnames(self):
        r = {"metadata": {"name": "git"}, "spec": {"hostnames": ["git.example.org"]}}
        self.assertEqual(app.to_entry("HTTPRoute", r)["url"], "https://git.example.org")

    def test_traefik_ingressroute_host_from_match(self):
        r = {"metadata": {"name": "tools"}, "spec": {"routes": [
            {"match": "PathPrefix(`/only`)"},
            {"match": "Host(`tools.example.org`) && PathPrefix(`/outpost.goauthentik.io/`)"},
            {"match": "Host(`other.example.org`)"},
        ]}}
        self.assertEqual(app.to_entry("IngressRoute", r)["url"], "https://tools.example.org")
        self.assertIsNone(app.to_entry("IngressRoute", {"metadata": {"name": "x"}, "spec": {"routes": [{"match": "HostRegexp(`.+`)"}]}}))
        self.assertIsNone(app.to_entry("IngressRoute", {"metadata": {"name": "y"}, "spec": {}}))

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

    def test_public_hides_probe_url(self):
        e = app.to_entry("Ingress", ing("a", "a.example.org", {"reyki.me/probe-url": "http://a.ns.svc/health"}))
        e["status"] = "up"
        self.assertEqual(app.public([e]), [{"name": "a", "description": "", "group": "", "url": "https://a.example.org", "status": "up"}])


class Status(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(app.classify(200, 100), "up")
        self.assertEqual(app.classify(302, 100), "up")
        self.assertEqual(app.classify(401, 100), "up")
        self.assertEqual(app.classify(200, app.SLOW_MS + 1), "degraded")
        self.assertEqual(app.classify(404, 100), "degraded")
        self.assertEqual(app.classify(502, 100), "down")
        self.assertEqual(app.classify(None, 0), "down")


class Page(unittest.TestCase):
    def test_personalise(self):
        with open(os.path.join(app.SITE_DIR, "index.html"), encoding="utf-8") as f:
            src = f.read()
        out = app.personalise(src, "mesh.reyki.net", "Internal services.")
        self.assertIn('content="/services.json"', out)
        self.assertIn("<h1 class=\"long\">mesh<span>.</span>reyki<span>.</span>net", out)
        self.assertIn("ssh mesh.reyki.net", out)
        self.assertIn("Internal services.", out)
        self.assertNotIn("api.reyki.me", out)
        self.assertIn("https://bitsandbricks.ch", out)


if __name__ == "__main__":
    unittest.main()
