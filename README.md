# reyki.me

reyki.me is the public domain for self-hosted services. This repo holds two things:

- **The reyki.me page** (`site/`): static, on GitHub Pages, so it stays up when the cluster is down.
  It loads the service list from `https://api.reyki.me/services.json` in the browser. If that does
  not answer, the page says `% cluster unreachable`.
- **The service list server** (`server/`): one small image, run twice in Kubernetes:
  - `deploy/public` → **api.reyki.me**, JSON only, only entries labelled `public`, CORS for https://reyki.me.
  - `deploy/mesh` → **mesh.reyki.net**, the full page served from the cluster, `public` + `internal` entries.

Same fonts and colours as [bitsandbricks.ch](https://bitsandbricks.ch). No cookies, no tracking,
no outside requests besides the list. Python standard library only.

## Listing a service

Label an `Ingress` (networking.k8s.io/v1), `HTTPRoute` (gateway.networking.k8s.io/v1) or Traefik
`IngressRoute` (traefik.io/v1alpha1, the link comes from the first Host rule in its routes):

```yaml
metadata:
  labels:
    reyki.me/listed: "public"      # reyki.me and mesh.reyki.net; "internal" = mesh.reyki.net only
  annotations:                     # all optional
    reyki.me/name: Grafana                     # default: the object's name
    reyki.me/description: Dashboards           # one line under the name
    reyki.me/group: Monitoring                 # heading it is grouped under
    reyki.me/url: https://grafana.reyki.net/   # default: https://<first host>
    reyki.me/order: "10"                       # sort inside the group, default 100
    reyki.me/probe: "false"                    # no status LED for this one
    reyki.me/probe-url: http://grafana.monitoring.svc:3000/api/health   # check this instead of the link
```

It shows up within 30 seconds. Wildcard hosts are skipped. The probe URL never leaves the server.

## Status LED

With `PROBE=true` (on in both overlays) the server checks each service from inside the cluster:

| LED | Meaning |
| --- | --- |
| green | answers with 2xx/3xx, or a login wall (401/403), within `SLOW_MS` (1500 ms) |
| orange | answers, but slowly, with another 4xx (e.g. 404), or with a bad TLS certificate |
| red | 5xx or no answer within `PROBE_TIMEOUT` (5 s) |
| none | probe turned off for this entry |

## Layout

| Path | What it is |
| --- | --- |
| `site/index.html` | The page. `<meta name="services">` says where the list comes from |
| `site/assets/services.js` | Loads and renders the list, refreshes every 60 s |
| `site/assets/site.css` | All styles, colour tokens at the top |
| `server/app.py` | The list server (`MODE=json` or `MODE=page`) |
| `tests/` | `python3 -m unittest discover -s tests` |
| `deploy/base` | Read-only RBAC (list ingresses, httproutes and ingressroutes), Deployment |
| `deploy/public`, `deploy/mesh` | The two instances, each with its Ingress |

## Running

- `main` → `.github/workflows/pages.yml` publishes `site/` (Settings > Pages > Source: **GitHub Actions**).
- `main` → `.github/workflows/image.yml` tests, renders the manifests and pushes
  `ghcr.io/bitsandbricks-ch/reyki.me:latest` and `:<sha>`. Pull requests only test and build.

```
kubectl create namespace reyki-me
kubectl apply -k deploy/public
kubectl apply -k deploy/mesh
```

Before the first apply:
- set `ingressClassName` and TLS in `deploy/public/ingress.yaml` and `deploy/mesh/ingress.yaml`;
- make the GHCR package public, or add an image pull secret;
- DNS: `api.reyki.me` → the public ingress, `mesh.reyki.net` → the mesh only.

**Keeping mesh.reyki.net private:** it is only private if its Ingress is served by a controller or
load balancer that listens on the mesh (NetBird / Tailscale) and nowhere public. If the same
public ingress controller serves it, anyone can reach it by sending `Host: mesh.reyki.net` to the
public IP, even when DNS only points into the mesh. Use a mesh-only ingress class (e.g. the
Tailscale operator's), or an IP allowlist for the mesh range on that Ingress.

Local run against a real cluster: `kubectl proxy --port 8001`, then
`KUBE_API=http://localhost:8001 MODE=page python3 server/app.py` and open http://localhost:8080.

| Env | Default | |
| --- | --- | --- |
| `MODE` | `page` | `page` (site + list) or `json` (list only) |
| `LABEL_SELECTOR` | `reyki.me/listed=public` | which objects to list |
| `ALLOW_ORIGIN` | empty | CORS origin for `/services.json` |
| `SITE_NAME`, `SITE_TAGLINE` | empty | rename the page in `page` mode |
| `PROBE`, `PROBE_TIMEOUT`, `SLOW_MS` | `false`, `5`, `1500` | status LED |
| `CACHE_SECONDS` | `30` | how often the list and status refresh |
| `PORT` | `8080` | |
