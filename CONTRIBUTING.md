# Contributing

Thanks for your interest in dex1-console. This tool can move a real gripper, so the rules below are stricter than usual
about safety and about what has actually been tested.

## Ground rules

- **Safety first.** Do not weaken the limits, the brake-on-error behaviour or the preflight gate without a clear reason.
  Anything that can move the hand needs a description of how it was tested.
- **Say what you tested.** In a pull request, state whether you tested with `--transport mock` only or on a real hand
  (which hand and motor id, host OS, adapter). Behaviour that was not tried on hardware must be marked "unverified" in
  the docs.
- **Do not guess.** Values that were not measured stay marked as choices or unverified. Do not fill them with estimates.
- **No hardware dumps.** Do not commit logs from a real run (`*.jsonl`), serial numbers, addresses of your network,
  tokens or photos of your environment.
- **English** for code comments, messages in `--help`, logs and docs. The UI text lives in `src/dex1_rs485/i18n.py`
  (English and Japanese).
- **No new runtime dependencies** for the protocol, the mock and the GUI. `pyftdi` and `pyserial` stay optional.

## Setup

Python 3.11 or newer.

```sh
git clone https://github.com/masayuki-kobayashi-aicle/dex1-console.git
cd dex1-console
pip install -e ".[dev,espprog]"
pytest                      # needs no hardware
dex1 selftest               # protocol check against recorded vendor SDK frames
dex1 gui --transport mock   # try the GUI without a hand
```

## Pull requests

- Keep each change small and explain why.
- Commit messages: `<type>: <description>` (feat, fix, refactor, docs, test, chore, perf, ci).
- CI must pass (tests on Python 3.11 and 3.12, and `dex1 selftest`).

## Security

Do not open a public issue for a vulnerability. See [SECURITY.md](SECURITY.md).
