# Contributing

Thank you for helping improve the Midnight 911 Home Assistant integration.

## Development setup

1. Create a virtualenv and install the same deps CI uses (Python 3.14):
   ```bash
   python3.14 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements_test.txt
   pip install sentry-sdk==2.66.1 bcrypt==4.3.0
   ```
   `pytest-homeassistant-custom-component` pulls in a matching Home Assistant
   core, so the venv also gives you a local `hass` binary.
2. Point a throwaway Home Assistant config directory at this checkout by
   symlinking the integration in:
   ```bash
   mkdir -p .ha_dev_config/custom_components
   ln -s "$(pwd)/custom_components/midnight_alerts" .ha_dev_config/custom_components/midnight_alerts
   ```
   `.ha_dev_config/` is gitignored, so it's safe to leave in place between
   runs — edits to the integration are picked up on restart without
   re-linking anything.
3. Run Home Assistant against that config:
   ```bash
   .venv/bin/hass -c .ha_dev_config --debug
   ```
   If port 8123 is already taken on your machine, add this to
   `.ha_dev_config/configuration.yaml` and use the new port instead:
   ```yaml
   http:
     server_port: 8124
   ```
4. Open the printed URL, complete onboarding, then add the integration via
   **Settings → Devices & services → Add Integration → "Midnight 911 Integration"**.

Logs land in `.ha_dev_config/home-assistant.log`.

## Running tests

```bash
source .venv/bin/activate
python -m pytest tests/ -q
```

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
