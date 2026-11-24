# Rules for coding agents

These rules are for AI coding agents (Claude Code, Codex, Copilot, opencode, ...) working on reyki.me.
Humans: the same rules apply to you in spirit. `CLAUDE.md` imports this file.

This repo follows the [BitsAndBricks handbook](https://github.com/bitsandbricks-ch/handbook),
profiles **static-site** and **service** (see `.mason.toml`,
[decision 0011](https://github.com/bitsandbricks-ch/handbook/blob/main/decisions/0011-several-profiles-per-repo.md)).
Read its core chapters and the blocks these profiles list. The rules below are only what is
specific to this repo.

| Folder | Profile |
| --- | --- |
| `site/`, `tools/check.py` | static-site (main) |
| `server/`, `tests/`, `deploy/`, `Dockerfile` | service |

## What this is

The reyki.me page (static, on GitHub Pages) and the small server that lists the self-hosted services from Kubernetes labels. The [README](README.md) says where things are and how to run it.

## Before you push

Run what CI runs (`.github/workflows/image.yml`) and make it pass:

- `python3 -m unittest discover -s tests -v`
- `python3 tools/check.py` (the page: links, assets, no outside requests, CSP)
- `kubectl kustomize deploy/public`
- `kubectl kustomize deploy/mesh`

## Differs from the handbook

- **No pre-commit hooks yet**: there is no `.pre-commit-config.yaml` ([decision 0010](https://github.com/bitsandbricks-ch/handbook/blob/main/decisions/0010-pre-commit.md)), so skip `pre-commit run --all-files` until it lands.
- **Plain HTML, not Astro** (static-site): the page is one hand-written file in `site/` with no build step.
- **Not headless** (service): the `deploy/mesh` instance serves the full page as well as the JSON.
- **No `/healthz` or `/metrics` yet** (service). TODO: add them or write down why not.

## Repo-specific rules

- Work from an issue: open one if there is none, comment when you start and when blocked, link it from the PR.
- Commits and PR titles follow Conventional Commits, with these scopes: `site`, `server`, `deploy`, `ci`.
- **Publishing:** every merge to `main` deploys the page and pushes the image. Nothing goes live except through a merged pull request.
- **No releases:** no version and no changelog
  ([decision 0012](https://github.com/bitsandbricks-ch/handbook/blob/main/decisions/0012-no-changelog-without-releases.md)).
- **No cookies, no tracking, no outside requests** besides the service list. Server: Python standard library only.
- **Public page:** no gaming, no real name, no employer or team names. Only entries labelled `public` reach api.reyki.me; never leak `internal` ones or probe URLs.
- Use the colour tokens at the top of `site/assets/site.css`, not raw colours.
- Stay inside the repository. Ask before deleting files you didn't create.
