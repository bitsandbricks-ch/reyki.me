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


class Guard(unittest.TestCase):
    def test_only_public_drops_internal_and_unlabelled(self):
        pub = ing("a", "a.example.org"); pub["metadata"]["labels"] = {"reyki.me/listed": "public"}
        internal = ing("b", "b.example.org"); internal["metadata"]["labels"] = {"reyki.me/listed": "internal"}
        bare = ing("c", "c.example.org")
        self.assertEqual(app.only_public([("Ingress", [pub, internal, bare])]), [("Ingress", [pub])])


class FakeKube:
    def __init__(self, results):
        self.results, self.calls = list(results), 0

    def listed(self):
        self.calls += 1
        r = self.results.pop(0) if self.results else self.last
        self.last = r
        if isinstance(r, Exception):
            raise r
        return r


class CacheTest(unittest.TestCase):
    def setUp(self):
        self.saved = (app.PROBE, app.CACHE_SECONDS, app.MODE)
        app.PROBE, app.MODE = False, "page"

    def tearDown(self):
        app.PROBE, app.CACHE_SECONDS, app.MODE = self.saved

    def names(self, cache):
        import json
        return [s["name"] for s in json.loads(cache.get())["services"]]

    def test_keeps_last_list_when_the_api_fails(self):
        app.CACHE_SECONDS = 0
        cache = app.Cache(FakeKube([[("Ingress", [ing("a", "a.example.org")])], OSError("down")]))
        self.assertEqual(self.names(cache), ["a"])
        cache.refresh()
        self.assertEqual(self.names(cache), ["a"])

    def test_serves_cached_list_without_listing_again(self):
        app.CACHE_SECONDS = 60
        kube = FakeKube([[("Ingress", [ing("a", "a.example.org")])]])
        cache = app.Cache(kube)
        self.assertEqual(self.names(cache), ["a"])
        self.assertEqual(self.names(cache), ["a"])
        self.assertEqual(kube.calls, 1)

    def test_stale_list_is_served_while_refreshing(self):
        import time
        app.CACHE_SECONDS = 0
        first = [("Ingress", [ing("a", "a.example.org")])]

        class Slow(FakeKube):
            def listed(self):
                if self.calls:
                    time.sleep(0.5)
                return super().listed()
        cache = app.Cache(Slow([first, [("Ingress", [ing("b", "b.example.org")])]]))
        self.assertEqual(self.names(cache), ["a"])
        start = time.monotonic()
        self.assertEqual(self.names(cache), ["a"])  # old list right away, refresh runs behind
        self.assertLess(time.monotonic() - start, 0.2)
        time.sleep(0.7)
        self.assertEqual(self.names(cache), ["b"])

    def test_json_mode_applies_the_public_guard(self):
        app.MODE, app.CACHE_SECONDS = "json", 60
        internal = ing("b", "b.example.org"); internal["metadata"]["labels"] = {"reyki.me/listed": "internal"}
        self.assertEqual(self.names(app.Cache(FakeKube([[("Ingress", [internal])]]))), [])


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

    def test_page_policy_allows_only_the_service_list(self):
        with open(os.path.join(app.SITE_DIR, "index.html"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("connect-src 'self' https://api.reyki.me;", src)
        # the server's own header policy replaces it; a renamed copy must not keep a stray one
        self.assertNotIn("Content-Security-Policy", app.personalise(src, "mesh.reyki.net", ""))
        self.assertNotIn("Content-Security-Policy", app.personalise(src, "", ""))


class Http(unittest.TestCase):
    """The real handler on a local port: headers, the list, static files and no way out of assets/."""

    @classmethod
    def setUpClass(cls):
        import threading
        from http.server import ThreadingHTTPServer
        cls.saved = (app.PROBE, app.CACHE_SECONDS, app.MODE, app.ALLOW_ORIGIN, app.Handler.cache, app.Handler.page)
        app.PROBE, app.CACHE_SECONDS, app.MODE, app.ALLOW_ORIGIN = False, 60, "page", "https://reyki.me"
        app.Handler.cache = app.Cache(FakeKube([[("Ingress", [ing("a", "a.example.org")])]]))
        app.Handler.page = b"<!doctype html><title>t</title>"
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        app.PROBE, app.CACHE_SECONDS, app.MODE, app.ALLOW_ORIGIN, app.Handler.cache, app.Handler.page = cls.saved

    def get(self, path, method="GET"):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=5)
        c.request(method, path)  # raw path: no client-side clean-up of ../
        r = c.getresponse()
        body = r.read()
        c.close()
        return r.status, dict((k.lower(), v) for k, v in r.getheaders()), body

    def test_every_answer_carries_the_security_headers(self):
        for path in ("/", "/services.json", "/assets/site.css", "/nope"):
            _, h, _ = self.get(path)
            self.assertIn("default-src 'none'", h["content-security-policy"], path)
            self.assertEqual(h["x-content-type-options"], "nosniff", path)
            self.assertEqual(h["referrer-policy"], "no-referrer", path)

    def test_list_is_json_with_cors_for_the_page_only(self):
        import json
        code, h, body = self.get("/services.json")
        self.assertEqual(code, 200)
        self.assertEqual(h["content-type"], "application/json")
        self.assertEqual(h["access-control-allow-origin"], "https://reyki.me")
        self.assertEqual([s["name"] for s in json.loads(body)["services"]], ["a"])
        self.assertNotIn("access-control-allow-origin", self.get("/")[1])

    def test_static_files_and_types(self):
        code, h, _ = self.get("/assets/services.js")
        self.assertEqual((code, h["content-type"]), (200, "text/javascript"))
        self.assertEqual(self.get("/assets/fonts/archivo-latin-standard-normal.woff2")[1]["content-type"], "font/woff2")

    def test_nothing_outside_assets_is_served(self):
        for path in ("/assets/../index.html", "/assets/..%2f..%2fserver%2fapp.py", "/assets/%2e%2e/%2e%2e/server/app.py",
                     "/assets/", "/server/app.py", "/CNAME", "/assets/fonts"):
            self.assertEqual(self.get(path)[0], 404, path)

    def test_head_has_no_body_and_health_answers(self):
        code, h, body = self.get("/", "HEAD")
        self.assertEqual((code, body), (200, b""))
        self.assertEqual(int(h["content-length"]), len(app.Handler.page))
        self.assertEqual(self.get("/healthz")[2], b"ok")


if __name__ == "__main__":
    unittest.main()
