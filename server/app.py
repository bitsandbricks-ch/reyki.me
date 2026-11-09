"""reyki.me service list: reads labelled Ingresses and HTTPRoutes from Kubernetes.

Two ways to run the same image:
  MODE=json  only /services.json (with CORS for ALLOW_ORIGIN). Used for api.reyki.me,
             the public page itself lives on GitHub Pages and loads the list in the browser.
  MODE=page  the page from site/ plus /services.json on the same host. Used for mesh.reyki.net.

Which objects are listed is the label selector (LABEL_SELECTOR):
  reyki.me/listed: "public"    on reyki.me and on mesh.reyki.net
  reyki.me/listed: "internal"  only on mesh.reyki.net

Annotations on a listed Ingress or HTTPRoute (all optional):
  reyki.me/name         shown name (default: the object's name)
  reyki.me/description  one line under the name
  reyki.me/group        heading the entry is grouped under
  reyki.me/url          link (default: https://<first host>)
  reyki.me/order        sort number inside its group (default 100)
  reyki.me/probe        "false": no status LED for this entry
  reyki.me/probe-url    check this URL instead of the link (e.g. http://grafana.monitoring.svc:3000/api/health)

Status (PROBE=true): up = answers in time with 2xx/3xx or a login wall (401/403),
degraded = slower than SLOW_MS, another 4xx, or a TLS certificate problem, down = 5xx or no answer.
Standard library only. Read-only in the cluster: list on ingresses and httproutes, nothing else.
"""

from html import escape
import json
import mimetypes
import os
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PREFIX = "reyki.me/"
MODE = os.environ.get("MODE", "page")
LABEL_SELECTOR = os.environ.get("LABEL_SELECTOR", "reyki.me/listed=public")
ALLOW_ORIGIN = os.environ.get("ALLOW_ORIGIN", "")
SITE_NAME = os.environ.get("SITE_NAME", "")
SITE_TAGLINE = os.environ.get("SITE_TAGLINE", "")
CACHE_SECONDS = int(os.environ.get("CACHE_SECONDS", "30"))
PROBE = os.environ.get("PROBE", "false").lower() == "true"
PROBE_TIMEOUT = float(os.environ.get("PROBE_TIMEOUT", "5"))
SLOW_MS = int(os.environ.get("SLOW_MS", "1500"))
PORT = int(os.environ.get("PORT", "8080"))
SITE_DIR = os.path.realpath(os.environ.get("SITE_DIR", os.path.join(os.path.dirname(__file__), "..", "site")))

SA_DIR = "/var/run/secrets/kubernetes.io/serviceaccount"
SOURCES = [
    ("Ingress", "/apis/networking.k8s.io/v1/ingresses"),
    ("HTTPRoute", "/apis/gateway.networking.k8s.io/v1/httproutes"),
]
CSP = ("default-src 'none'; script-src 'self'; connect-src 'self'; style-src 'self'; img-src 'self'; "
       "font-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


# ---- Turning Kubernetes objects into entries (pure functions, tested) ----

def first_host(kind, obj):
    spec = obj.get("spec") or {}
    if kind == "Ingress":
        for rule in spec.get("rules") or []:
            if rule.get("host"):
                return rule["host"]
        for tls in spec.get("tls") or []:
            for host in tls.get("hosts") or []:
                return host
        return None
    for host in spec.get("hostnames") or []:
        return host
    return None


def is_http(url):
    return isinstance(url, str) and url.startswith(("https://", "http://"))


def to_entry(kind, obj):
    """One listed object -> one entry, or None when it has no usable link."""
    meta = obj.get("metadata") or {}
    ann = meta.get("annotations") or {}
    url = ann.get(PREFIX + "url")
    if not url:
        host = first_host(kind, obj)
        if not host or "*" in host:
            return None
        url = "https://" + host
    if not is_http(url):
        return None
    try:
        order = int(ann.get(PREFIX + "order", "100"))
    except ValueError:
        order = 100
    probe_url = ann.get(PREFIX + "probe-url") or url
    return {
        "name": ann.get(PREFIX + "name") or meta.get("name", ""),
        "description": ann.get(PREFIX + "description", ""),
        "group": ann.get(PREFIX + "group", ""),
        "url": url,
        "order": order,
        "probe": probe_url if ann.get(PREFIX + "probe", "true").lower() != "false" and is_http(probe_url) else None,
    }


def build(items_by_kind):
    """[(kind, [obj, ...]), ...] -> sorted entries, one per URL."""
    seen, entries = set(), []
    for kind, items in items_by_kind:
        for obj in items:
            entry = to_entry(kind, obj)
            if entry and entry["url"] not in seen:
                seen.add(entry["url"])
                entries.append(entry)
    entries.sort(key=lambda e: (e["group"].lower(), e["order"], e["name"].lower()))
    return entries


def public(entries):
    """What leaves the server: no probe URLs (they can be cluster-internal), no sort keys."""
    keep = ("name", "description", "group", "url", "status")
    return [{k: e[k] for k in keep if k in e} for e in entries]


def classify(code, ms):
    """HTTP status (None = no answer) and response time -> up / degraded / down."""
    if code is None or code >= 500:
        return "down"
    if code >= 400 and code not in (401, 403, 407):
        return "degraded"
    return "degraded" if ms > SLOW_MS else "up"


def personalise(html_text, name, tagline):
    """The page template, renamed for another host (mesh.reyki.net) and pointed at /services.json."""
    html_text = html_text.replace('content="https://api.reyki.me/services.json"', 'content="/services.json"')
    if name:
        n = escape(name)
        h1 = "<h1 class=\"long\">" if len(name) > 10 else "<h1>"
        html_text = html_text.replace("<h1>reyki<span>.</span>me", h1 + n.replace(".", "<span>.</span>"))
        html_text = html_text.replace("reyki.me", n)
    if tagline:
        html_text = html_text.replace("Self-hosted services.", escape(tagline))
    return html_text


# ---- Talking to the API server ----

class Kube:
    def __init__(self):
        host = os.environ.get("KUBERNETES_SERVICE_HOST")
        port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
        self.base = os.environ.get("KUBE_API", f"https://{host}:{port}")
        ca = os.path.join(SA_DIR, "ca.crt")
        self.ctx = ssl.create_default_context(cafile=ca) if os.path.exists(ca) else None

    def get(self, path):
        req = urllib.request.Request(self.base + path + "?labelSelector=" + urllib.parse.quote(LABEL_SELECTOR, safe=""))
        token_file = os.path.join(SA_DIR, "token")
        if os.path.exists(token_file):  # read every time: projected tokens rotate
            with open(token_file) as f:
                req.add_header("Authorization", "Bearer " + f.read().strip())
        with urllib.request.urlopen(req, timeout=10, context=self.ctx) as res:
            return json.load(res).get("items") or []

    def listed(self):
        out = []
        for kind, path in SOURCES:
            try:
                out.append((kind, self.get(path)))
            except urllib.error.HTTPError as e:
                if e.code != 404:  # 404 just means Gateway API is not installed
                    print(f"list {kind}: HTTP {e.code}", flush=True)
            except (urllib.error.URLError, OSError, ValueError) as e:
                print(f"list {kind}: {e}", flush=True)
        return out


def probe(url):
    req = urllib.request.Request(url, headers={"User-Agent": "reyki.me-status"})
    start = time.monotonic()
    ms = lambda: (time.monotonic() - start) * 1000
    try:
        with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT) as res:
            return classify(res.status, ms())
    except urllib.error.HTTPError as e:
        return classify(e.code, ms())
    except urllib.error.URLError as e:
        if isinstance(e.reason, ssl.SSLCertVerificationError):
            return "degraded"  # it answers, but the certificate is wrong or expired
        return "down"
    except Exception:
        return "down"


# ---- Cache and HTTP ----

class Cache:
    def __init__(self, kube):
        self.kube, self.lock, self.at, self.json = kube, threading.Lock(), float("-inf"), b'{"services":[]}'

    def get(self):
        with self.lock:
            if time.monotonic() - self.at >= CACHE_SECONDS:
                entries = build(self.kube.listed())
                if PROBE:
                    todo = [e for e in entries if e["probe"]]
                    with ThreadPoolExecutor(max_workers=8) as pool:
                        for e, status in zip(todo, pool.map(lambda e: probe(e["probe"]), todo)):
                            e["status"] = status
                self.json = json.dumps({"services": public(entries)}, separators=(",", ":")).encode()
                self.at = time.monotonic()
            return self.json


class Handler(BaseHTTPRequestHandler):
    cache = None
    page = b""
    server_version = "reyki.me"
    sys_version = ""

    def do_HEAD(self):
        self.do_GET(head=True)

    def do_OPTIONS(self):
        self.send(204, b"", "text/plain", cors=True)

    def do_GET(self, head=False):
        path = urllib.parse.urlsplit(self.path).path
        if path == "/healthz":
            return self.send(200, b"ok", "text/plain", head)
        if path == "/services.json":
            return self.send(200, self.cache.get(), "application/json", head, CACHE_SECONDS, cors=True)
        if MODE == "page":
            if path in ("/", "/index.html"):
                return self.send(200, self.page, "text/html; charset=utf-8", head, 300)
            if path.startswith("/assets/"):
                file = os.path.realpath(os.path.join(SITE_DIR, urllib.parse.unquote(path).lstrip("/")))
                if file.startswith(os.path.join(SITE_DIR, "assets") + os.sep) and os.path.isfile(file):
                    with open(file, "rb") as f:
                        body = f.read()
                    ctype = mimetypes.guess_type(file)[0] or "application/octet-stream"
                    return self.send(200, body, ctype, head, 3600)
        self.send(404, b"not found\n", "text/plain", head)

    def send(self, code, body, ctype, head=False, max_age=0, cors=False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", f"public, max-age={max_age}" if max_age else "no-store")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if cors and ALLOW_ORIGIN:
            self.send_header("Access-Control-Allow-Origin", ALLOW_ORIGIN)
            self.send_header("Access-Control-Allow-Methods", "GET")
            self.send_header("Vary", "Origin")
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("text/javascript", ".js")


def main():
    if MODE not in ("page", "json"):
        raise SystemExit("MODE must be page or json")
    Handler.cache = Cache(Kube())
    if MODE == "page":
        with open(os.path.join(SITE_DIR, "index.html"), encoding="utf-8") as f:
            Handler.page = personalise(f.read(), SITE_NAME, SITE_TAGLINE).encode()
    print(f"mode {MODE} on :{PORT}, selector {LABEL_SELECTOR}, probe {PROBE}", flush=True)
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
