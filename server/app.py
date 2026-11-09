"""reyki.me: serves the landing page and fills its services list from Kubernetes.

Lists the Ingresses and HTTPRoutes in the cluster that carry the label
reyki.me/listed=true and renders them into the page, server side (no JavaScript).
Standard library only. Read-only: it needs list on ingresses and httproutes, nothing else.

Annotations on a listed Ingress or HTTPRoute (all optional):
  reyki.me/name         shown name (default: the object's name)
  reyki.me/description  one line under the name
  reyki.me/group        heading the entry is grouped under
  reyki.me/url          link (default: https://<first host>)
  reyki.me/order        sort number inside its group (default 100)
  reyki.me/probe        "false" skips the up/down check for this entry

Routes: /  the page,  /assets/...  static files,  /services.json  the same list as JSON,  /healthz
"""

import html
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
LABEL_SELECTOR = os.environ.get("LABEL_SELECTOR", "reyki.me/listed=true")
CACHE_SECONDS = int(os.environ.get("CACHE_SECONDS", "30"))
PROBE = os.environ.get("PROBE", "false").lower() == "true"
PROBE_TIMEOUT = float(os.environ.get("PROBE_TIMEOUT", "3"))
PORT = int(os.environ.get("PORT", "8080"))
SITE_DIR = os.path.realpath(os.environ.get("SITE_DIR", os.path.join(os.path.dirname(__file__), "..", "site")))
MARKER = "<!--SERVICES-->"

SA_DIR = "/var/run/secrets/kubernetes.io/serviceaccount"
SOURCES = [
    ("Ingress", "/apis/networking.k8s.io/v1/ingresses"),
    ("HTTPRoute", "/apis/gateway.networking.k8s.io/v1/httproutes"),
]
CSP = "default-src 'none'; style-src 'self'; img-src 'self'; font-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"


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
    if not url.startswith(("https://", "http://")):
        return None
    try:
        order = int(ann.get(PREFIX + "order", "100"))
    except ValueError:
        order = 100
    return {
        "name": ann.get(PREFIX + "name") or meta.get("name", ""),
        "description": ann.get(PREFIX + "description", ""),
        "group": ann.get(PREFIX + "group", ""),
        "url": url,
        "order": order,
        "probe": ann.get(PREFIX + "probe", "true").lower() != "false",
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


def render(entries):
    """Entries -> the services section. Empty string when there is nothing to list."""
    if not entries:
        return ""
    esc = lambda s: html.escape(s, quote=True)
    out = ['<section class="services" aria-labelledby="svc">', '  <p class="prompt" id="svc"><b>$</b> show services</p>']
    group = None
    for e in entries:
        if e["group"] != group:
            if group is not None:
                out.append("  </ul>")
            group = e["group"]
            if group:
                out.append(f'  <p class="group">{esc(group)}</p>')
            out.append("  <ul>")
        shown = urllib.parse.urlsplit(e["url"]).netloc or e["url"]
        led = ""
        if e.get("status") in ("up", "down"):
            led = f'<span class="led {e["status"]}" title="{e["status"]}"></span>'
        what = f'<span class="what">{esc(e["description"])}</span>' if e["description"] else ""
        out.append(f'    <li><a href="{esc(e["url"])}"><span class="name">{led}{esc(e["name"])}</span>'
                   f'<span class="url">{esc(shown)}</span></a>{what}</li>')
    out += ["  </ul>", "</section>"]
    return "\n".join(out)


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
    req = urllib.request.Request(url, headers={"User-Agent": "reyki.me"})
    try:
        with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT) as res:
            return "up" if res.status < 500 else "down"
    except urllib.error.HTTPError as e:
        return "up" if e.code < 500 else "down"  # a 401/403 login wall still answers
    except Exception:
        return "down"


# ---- Cache and HTTP ----

class Cache:
    def __init__(self, kube):
        self.kube, self.lock, self.at = kube, threading.Lock(), float("-inf")
        with open(os.path.join(SITE_DIR, "index.html"), encoding="utf-8") as f:
            self.template = f.read()
        self.page, self.json = b"", b""

    def refresh(self):
        with self.lock:
            if time.monotonic() - self.at < CACHE_SECONDS:
                return
            entries = build(self.kube.listed())
            if PROBE:
                todo = [e for e in entries if e["probe"]]
                with ThreadPoolExecutor(max_workers=8) as pool:
                    for e, status in zip(todo, pool.map(lambda e: probe(e["url"]), todo)):
                        e["status"] = status
            self.page = self.template.replace(MARKER, render(entries)).encode()
            public = [{k: v for k, v in e.items() if k not in ("order", "probe")} for e in entries]
            self.json = json.dumps({"services": public}, separators=(",", ":")).encode()
            self.at = time.monotonic()


class Handler(BaseHTTPRequestHandler):
    cache = None
    server_version = "reyki.me"
    sys_version = ""

    def do_HEAD(self):
        self.do_GET(head=True)

    def do_GET(self, head=False):
        path = urllib.parse.urlsplit(self.path).path
        if path == "/healthz":
            return self.send(200, b"ok", "text/plain", head)
        if path in ("/", "/index.html"):
            self.cache.refresh()
            return self.send(200, self.cache.page, "text/html; charset=utf-8", head, CACHE_SECONDS)
        if path == "/services.json":
            self.cache.refresh()
            return self.send(200, self.cache.json, "application/json", head, CACHE_SECONDS)
        if path.startswith("/assets/"):
            file = os.path.realpath(os.path.join(SITE_DIR, urllib.parse.unquote(path).lstrip("/")))
            if file.startswith(os.path.join(SITE_DIR, "assets") + os.sep) and os.path.isfile(file):
                with open(file, "rb") as f:
                    body = f.read()
                ctype = mimetypes.guess_type(file)[0] or "application/octet-stream"
                return self.send(200, body, ctype, head, 86400)
        self.send(404, b"not found\n", "text/plain", head)

    def send(self, code, body, ctype, head=False, max_age=0):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", f"public, max-age={max_age}" if max_age else "no-store")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("image/svg+xml", ".svg")


def main():
    Handler.cache = Cache(Kube())
    print(f"listening on :{PORT}, selector {LABEL_SELECTOR}, probe {PROBE}", flush=True)
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
