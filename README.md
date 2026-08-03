# Midnight 911 for Home Assistant

[![License][license-shield]](LICENSE)
[![GitHub Release][releases-shield]][releases]
[![HA and HACS Validate](https://github.com/midnight-security/midnight-homeassistant-911/actions/workflows/ha_and_hacs_validate.yml/badge.svg)](https://github.com/midnight-security/midnight-homeassistant-911/actions/workflows/ha_and_hacs_validate.yml)
[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/integration)

The Midnight 911 integration for Home Assistant allows anyone to add professional security monitoring to their home.

Users can add either a button or automation that triggers an alert to a US-based security monitoring center. If validated or without response, they will contact your local 911 center on your behalf. So please use it carefully.

HACS is required, currently.

> **Note:** This integration is currently available in the United States only, with plans to expand to Canada.

> **Roadmap:** This is a HACS-distributed custom integration today. We're working toward eventual inclusion in Home Assistant Core — see [`CORE_INTEGRATION.md`](CORE_INTEGRATION.md) for that checklist.

---

## How it Works

This integration works in partnership with RapidSOS and uses their service to validate 911 calls and reach the associated 911 center.

It's VERY IMPORTANT you keep the address updated properly.

---

## Installation

### HACS (Recommended)

1. Open HACS in your Home Assistant instance ![App Screenshot](img/1.HACS.png)
2. Click on the three dots menu and choose "Custom Repository" ![App Screenshot](img/2.HACS-Meatball.png)
3. Enter the url for this repo in the dialog and click Add ![App Screenshot](img/3.HACS-CustomRepo.png)
4. Now hit cancel on the dialog, the integration should appear in "New" ![App Screenshot](img/4.HACS-New.png)
5. Click "Download" under the three dot menu. ![App Screenshot](img/5.HACS-Download.png)
6. The integration should now appear in "Pending Restart" ![App Screenshot](img/6.HACS-Pending.png)
7. In Settings the restart button should be at the top. ![App Screenshot](img/7.Setting-Restart.png)
8. After restarting the integration should be available if you search for it from the dashbaord. ![App Screenshot](img/8.Dash-verify.png)

### Manual

1. Copy the `custom_components/midnight_alerts` folder to your Home Assistant `custom_components` directory
2. Restart Home Assistant

---

## Warnings & Disclaimers

Home Assistant must have an active internet connection for the integration to work properly.

NO GUARANTEE
This integration is provided as-is without warranties of any kind. Home Assistant and Midnight both involve multiple service providers and potential points of failure, including (but not limited to) your internet service provider, 3rd party hosting services such as Amazon Web Services, and the Home Assistant software platform.

Please read and understand the [Midnight Terms of Service](https://www.midnight.security/legal) and [Home Assistant Terms of Service](https://www.home-assistant.io/tos/) both of which include important limitations of liability and indemnification provisions.

---

## Development

### Branch workflow

- **`develop`** — active development branch
- **`master`** — production branch; merges here trigger releases

Work happens on `develop`. When ready, open a PR to merge `develop` → `master`.

### Releases & versioning

Releases are automated with [semantic-release](https://github.com/semantic-release/semantic-release) via the [Release](.github/workflows/release.yml) workflow. When a push to `master` includes releasable commits, the workflow:

1. Bumps the version in `package.json` and `custom_components/midnight_alerts/manifest.json`
2. Builds `midnight_alerts.zip` and attaches it to a GitHub Release (for HACS)
3. Commits the version bump to **`master`**
4. Merges **`master`** back into **`develop`** via [`semantic-release-backmerge`](https://github.com/saitho/semantic-release-backmerge)

```
develop → PR → master → semantic-release → version commit on master → back-merge into develop
```

To preview the next release locally:

```bash
yarn install
yarn semantic-release --dry-run   # must be on master
```

### Commit messages

This project uses [Conventional Commits](https://www.conventionalcommits.org/). The commit prefix determines the version bump:

| Prefix | Version bump | Example |
|--------|--------------|---------|
| `fix:` | Patch (`0.4.0` → `0.4.1`) | `fix: handle API timeout` |
| `feat:` | Minor (`0.4.0` → `0.5.0`) | `feat: add automation trigger` |
| `feat!:` or `BREAKING CHANGE:` | Major (`0.4.0` → `1.0.0`) | `feat!: change alert payload` |
| `chore:`, `docs:`, etc. | No release | `docs: update install steps` |

Only commits with `fix:`, `feat:`, or breaking changes trigger a new release.

---

## License

Copyright 2026 Midnight Security, Inc.

Licensed under the [Apache License, Version 2.0](LICENSE).

[license-shield]: https://img.shields.io/github/license/midnight-security/midnight-homeassistant-911.svg
[releases-shield]: https://img.shields.io/github/release/midnight-security/midnight-homeassistant-911.svg
[releases]: https://github.com/midnight-security/midnight-homeassistant-911/releases
