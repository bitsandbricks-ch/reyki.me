"""Checks site/ before it is published: local links and assets exist, #anchors exist, no outside
requests (scripts, styles, fonts, images load from this site only), one <h1>, lang and <title>,
unique ids, alt text on images, and a Content-Security-Policy whose only outside address is the
service list. Python standard library only.

    python3 tools/check.py
"""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
import re
import sys

SITE = Path(__file__).resolve().parent.parent / "site"
# Attributes that make the browser fetch something by itself (not links the reader clicks)
# The page's one outside request: the service list (the page reads its address from <meta name="services">)
ALLOWED = {"https://api.reyki.me"}
LOADS = {("script", "src"), ("link", "href"), ("img", "src"), ("source", "src"), ("iframe", "src"), ("video", "src"), ("audio", "src")}


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs, self.ids, self.h1, self.lang, self.title, self.no_alt, self.csp = [], [], 0, None, False, 0, None
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta" and (a.get("http-equiv") or "").lower() == "content-security-policy":
            self.csp = a.get("content") or ""
        if tag == "script" and not a.get("src"):
            self.inline_script = True
        if tag == "html":
            self.lang = a.get("lang")
        if tag == "h1":
            self.h1 += 1
        if tag == "title":
            self._in_title = True
        if tag == "img" and a.get("alt") is None:
            self.no_alt += 1
        if "id" in a:
            self.ids.append(a["id"])
        for name, value in attrs:
            if name in ("href", "src") and value:
                load = (tag, name) in LOADS and not (tag == "link" and a.get("rel") not in ("stylesheet", "preload", "icon", "modulepreload"))
                self.refs.append((tag, value, load))

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title and data.strip():
            self.title = True


def check(path):
    errors = []
    page = Page()
    page.feed(path.read_text(encoding="utf-8"))
    rel = path.relative_to(SITE)
    if not page.lang:
        errors.append("no lang on <html>")
    if not page.title:
        errors.append("no <title>")
    if page.h1 != 1:
        errors.append(f"{page.h1} <h1> elements, want 1")
    if page.csp is None:
        errors.append("no Content-Security-Policy meta")
    else:
        outside = sorted(set(re.findall(r"https?://[^\s;']+", page.csp)) - ALLOWED)
        if outside:
            errors.append("CSP allows outside addresses: " + ", ".join(outside))
        if re.search(r"(^|\s)(\*|https?:)(?=[\s;]|$)", page.csp):
            errors.append("CSP allows any site (* or a bare scheme)")
        if "'unsafe-inline'" in page.csp or "'unsafe-eval'" in page.csp:
            errors.append("CSP allows inline or eval code")
    if getattr(page, "inline_script", False):
        errors.append("inline <script> (put it in assets/)")
    if page.no_alt:
        errors.append(f"{page.no_alt} <img> without alt")
    dupes = sorted({i for i in page.ids if page.ids.count(i) > 1})
    if dupes:
        errors.append("duplicate ids: " + ", ".join(dupes))
    for tag, ref, load in page.refs:
        url = urlsplit(ref)
        if url.scheme in ("mailto", "tel"):
            continue
        if url.scheme or url.netloc:
            if load:
                errors.append(f"outside request: <{tag}> {ref}")
            continue
        if not url.path:  # #anchor on this page
            if url.fragment and url.fragment not in page.ids:
                errors.append(f"missing anchor: {ref}")
            continue
        target = (SITE / url.path.lstrip("/")) if url.path.startswith("/") else (path.parent / url.path)
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            errors.append(f"missing file: {ref}")
    return [f"{rel}: {e}" for e in errors]


def main():
    pages = sorted(SITE.rglob("*.html"))
    errors = [e for p in pages for e in check(p)]
    css = "\n".join(p.read_text(encoding="utf-8") for p in SITE.rglob("*.css"))
    for ref in re.findall(r"url\(\s*['\"]?([^'\")]+)", css):
        if re.match(r"^(https?:)?//", ref):
            errors.append(f"css: outside request: {ref}")
        elif not ref.startswith("data:") and not (SITE / ref.lstrip("/")).is_file() and not any((p.parent / ref).is_file() for p in SITE.rglob("*.css")):
            errors.append(f"css: missing file: {ref}")
    for e in errors:
        print(e)
    print(f"{'site ok' if not errors else f'{len(errors)} problems'}: {len(pages)} pages checked")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
