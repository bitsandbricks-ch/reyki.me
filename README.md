# reyki.me

Landing page for reyki.me, the public domain for self-hosted services.
Plain static HTML, no build step, no cookies, no tracking, no outside requests.
Same fonts and colours as [bitsandbricks.ch](https://bitsandbricks.ch), its own layout.

| Path | What it is |
| --- | --- |
| `index.html` | The page. The services list is at the bottom, with a copy-paste example in a comment |
| `assets/site.css` | All styles, colour tokens at the top (light and dark follow the system) |
| `assets/favicon.svg` | The `>_` mark |
| `assets/fonts/` | Archivo and IBM Plex Mono (SIL OFL 1.1) |
| `CNAME` | Custom domain for GitHub Pages |

## Adding a service

In `index.html`, remove `hidden` from `<section class="services">` and add one line per tool:

```html
<li><a href="https://name.reyki.me"><span class="name">Name</span><span class="url">name.reyki.me</span></a><span class="what">What it is</span></li>
```

## Hosting

GitHub Pages, Settings > Pages > Source: "Deploy from a branch", `main`, `/ (root)`.
DNS for the apex `reyki.me`: A records `185.199.108.153`, `185.199.109.153`, `185.199.110.153`,
`185.199.111.153` (and AAAA `2606:50c0:8000::153` to `2606:50c0:8003::153` for IPv6).
