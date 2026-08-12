# Security Policy

## Reporting a Vulnerability

The Midnight 911 Home Assistant integration handles life-safety alerting. If you
believe you have found a security vulnerability, please report it responsibly.

**Do not open a public GitHub issue for security vulnerabilities.**

Instead, email **engineering@midnight.security** with:

- A description of the vulnerability and its potential impact
- Steps to reproduce, including affected versions
- Any proof-of-concept code or screenshots (if applicable)
- Your contact information for follow-up

We aim to acknowledge reports within **3 business days** and will work with you
on a coordinated disclosure timeline.

## Important: Do Not Test With Real Alerts

This integration triggers professional security monitoring and may result in
emergency services dispatch. **Never test vulnerabilities by triggering real
alerts or 911 calls.** Use a development environment with a test API key when
possible, and describe theoretical or code-level issues in your report instead.

## Supported Versions

| Version | Supported |
| ------- | --------- |
| Latest release | Yes |
| Older releases | No |

We recommend running the latest release available from this repository or HACS.

## Scope

The following are **in scope**:

- Vulnerabilities in the `midnight_alerts` Home Assistant integration code
- Issues that could lead to unauthorized alert triggering
- Improper handling of API keys or credentials stored by the integration
- Authentication or authorization flaws in how the integration communicates with
  the Midnight Alerts API

The following are **out of scope**:

- Vulnerabilities in Home Assistant core or other third-party integrations
- Issues in the Midnight Alerts backend API (report those to security@midnight.security
  separately — they will be routed appropriately)
- Social engineering, physical security, or denial-of-service attacks
- Missing security features in unsupported or end-of-life versions

## Safe Harbor

We consider security research conducted in good faith, consistent with this
policy, to be authorized. We will not pursue legal action against researchers
who follow these guidelines.

## Recognition

We appreciate responsible disclosure. With your permission, we are happy to
acknowledge your contribution when we publish a fix.
