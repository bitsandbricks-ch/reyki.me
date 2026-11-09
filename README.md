# reyki.me

Landing page for reyki.me, the public domain for self-hosted services. It runs as one small
container in Kubernetes and lists every Ingress or HTTPRoute that carries the label
`reyki.me/listed: "true"`. Add the label to a service and it shows up on the page within 30 seconds.

Same fonts and colours as [bitsandbricks.ch](https://bitsandbricks.ch), its own layout.
Server side rendered, no JavaScript, no cookies, no tracking, no outside requests, Python standard library only.

## Listing a service

```yaml
metadata:
  labels:
    reyki.me/listed: "true"
  annotations:                                # all optional
    reyki.me/name: Grafana                    # default: the object's name
    reyki.me/description: Dashboards          # one line under the name
    reyki.me/group: Monitoring                # heading it is grouped under
    reyki.me/url: https://grafana.reyki.me/   # default: https://<first host>
    reyki.me/order: "10"                      # sort inside the group, default 100
    reyki.me/probe: "false"                   # no up/down LED for this one
```

Works on `Ingress` (networking.k8s.io/v1) and `HTTPRoute` (gateway.networking.k8s.io/v1; skipped
when Gateway API is not installed). Wildcard hosts are skipped. With `PROBE=true` the server
requests each link from inside the cluster and shows a green (answers) or orange (no answer, 5xx) LED.

## Layout

| Path | What it is |
| --- | --- |
| `site/index.html` | The page. `<!--SERVICES-->` is where the list goes |
| `site/assets/` | `site.css` (colour tokens at the top), favicon, fonts (SIL OFL 1.1) |
| `server/app.py` | Lists labelled Ingresses and HTTPRoutes, renders the page, serves `/`, `/assets/`, `/services.json`, `/healthz` |
| `tests/` | `python3 -m unittest discover -s tests` |
| `deploy/` | Kustomize: namespace, read-only RBAC, Deployment, Service, Ingress |
| `Dockerfile` | `python:3.13-alpine`, runs as uid 10001 |

## Running

Pushing to `main` tests, builds and pushes `ghcr.io/bitsandbricks-ch/reyki.me:latest` (and `:<sha>`).
Pull requests only test and build.

```
kubectl apply -k deploy/
```

Before the first apply: set `ingressClassName` and TLS in `deploy/ingress.yaml`, and either make the
GHCR package public or add an image pull secret. Point `reyki.me` DNS at the ingress.

Local run against a cluster, without the in-cluster token: `kubectl proxy --port 8001` then
`KUBE_API=http://localhost:8001 python3 server/app.py` and open http://localhost:8080.

| Env | Default | |
| --- | --- | --- |
| `LABEL_SELECTOR` | `reyki.me/listed=true` | which objects to list |
| `PROBE` | `false` (`true` in `deploy/`) | up/down LED per service |
| `PROBE_TIMEOUT` | `3` | seconds per probe |
| `CACHE_SECONDS` | `30` | how often the list is refreshed |
| `PORT` | `8080` | |
