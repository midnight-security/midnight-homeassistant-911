# Contributing

Thank you for helping improve the Midnight 911 Home Assistant integration.

## Development setup

1. Clone this repository into your Home Assistant `custom_components` path, or symlink `custom_components/midnight_alerts` into a dev instance.
2. Restart Home Assistant and add the integration via **Settings → Devices & services**.

## Vendored Alarmo code

`custom_components/midnight_alerts/alarmo/` contains Alarmo's integration
code, vendored in via [`git subtree`](https://manpages.debian.org/unstable/git-man/git-subtree.1.en.html)
from our fork, [`midnight-security/alarmo`](https://github.com/midnight-security/alarmo)
(itself a fork of [`nielsfaber/alarmo`](https://github.com/nielsfaber/alarmo)).
It's ordinary tracked files, not a submodule — no extra clone/init step is
needed, and it can be edited in place like any other file in this repo.

This exists so Alarmo's alarm-panel logic can eventually be adapted to run
under the `midnight_alerts` domain (see the plan to fold it into our own
`async_setup_entry`), while still being able to pull in upstream Alarmo
fixes later instead of hand-copying them.

### Pulling in upstream updates

1. On GitHub, merge `nielsfaber/alarmo`'s `main` into our fork's `main` so
   `midnight-security/alarmo` stays current with upstream.
2. Locally, in this repo (add the remote once if you don't already have it:
   `git remote add alarmo-fork https://github.com/midnight-security/alarmo.git`):
   ```bash
   git fetch alarmo-fork
   git subtree split --prefix=custom_components/alarmo -b alarmo-core alarmo-fork/main
   git subtree pull --prefix=custom_components/midnight_alerts/alarmo alarmo-core --squash
   ```
   `custom_components/alarmo` here refers to the path *inside the fork*
   (its own repo root), not a path in this repo — `git subtree split`
   requires that path to exist on disk as a placeholder in the current
   working tree first (e.g. `mkdir -p custom_components/alarmo`, removed
   again afterwards); it isn't otherwise used.
3. Resolve any conflicts from local adaptations the same as a normal merge,
   then commit.

## Branch workflow

- **`develop`** — active development
- **`master`** — production; merges here trigger semantic-release

Open PRs against `develop`. When ready for release, merge `develop` → `master`.

## Commit messages

This project uses [Conventional Commits](https://www.conventionalcommits.org/):

| Prefix | Version bump |
|--------|--------------|
| `fix:` | Patch |
| `feat:` | Minor |
| `feat!:` or `BREAKING CHANGE:` | Major |
| `docs:`, `chore:`, etc. | No release |

## Validation

CI runs [hassfest](https://github.com/home-assistant/actions/tree/master/hassfest) and [HACS validation](https://github.com/hacs/action) on every push and PR.

Run locally before opening a PR:

```bash
# Requires Docker
docker run --rm -v $(pwd):/github/workspace ghcr.io/home-assistant/hassfest
```

## Security

Do not open public issues for security vulnerabilities. See [SECURITY.md](SECURITY.md).
