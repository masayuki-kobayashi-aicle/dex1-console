# Security policy

## Reporting a vulnerability

Please report it privately with GitHub's **Report a vulnerability** button on the
[Security tab](https://github.com/masayuki-kobayashi-aicle/dex1-console/security/advisories/new). Do not open a public
issue or pull request for it.

This tool drives a real actuator, so a report about a safety problem counts too. Examples: a way to make the hand move
outside the configured limits, to skip the preflight gate or the brake, or to command the hand from a web page (the GUI
listens on `127.0.0.1` only, checks the Host header and needs a per-run token).

This is a personal project maintained on a best-effort basis. There is no guaranteed response time and there are no bug
bounties.

## Supported versions

Only the latest release on `main` is supported. The project is a pre-release (0.1.x).

## Scope

- In scope: the code in this repository (`src/dex1_rs485/`, including the local web GUI).
- Out of scope: Unitree's hardware and firmware, and the third-party packages `pyftdi`, `pyserial` and `rerun-sdk`.
  Report those to their own projects.
