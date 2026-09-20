# Contributing to Airscope

Airscope is a userland 802.11 auditing tool that talks to USB Wi-Fi cards directly over PyUSB.
Contributions welcome: chipset drivers, attacks, UI/UX, bug fixes, docs.

Two things first:

- **Authorized use only.** Airscope is for networks you own or are explicitly authorized to test.
- **Hardware-damage risk is real.** Register + firmware access can permanently brick a card.
  Test driver work on hardware you can afford to lose. We only ever write RAM/registers and
  replay the vendor download path — never EFUSE/EEPROM fuses, and a PR that does will be rejected.

## Dev setup

This repo uses **uv**:

```
uv sync --group dev          # install (editable + dev deps)
uv run airscope              # run
uv run pytest                # tests: no hardware needed, USB is mocked
uv run ruff check src/       # lint (never `ruff format`; see below)
uv run pyinstaller airscope.spec --noconfirm   # binary -> dist/airscope[.exe]
```

PyInstaller doesn't cross-compile: build each target on that OS. Don't run `ruff format` —
the tree is hand-formatted and the formatter is disabled repo-wide; match surrounding style by hand.

## Commits & pull requests

- Conventional-commit prefix with a scope: `fix(8822bu): …`, `feat(scanner): …`, `docs: …`.
  One logical change per commit.
- PR body: what changed and why. For driver work, note what was hardware-tested vs pcap-only.
- Keep real network identifiers out of commits, PRs, logs, and fixtures (SSIDs, BSSIDs, MACs,
  hostnames): generalize or redact to `aa:bb:cc:**:**:**`.

## Licensing

By submitting a PR you agree your contribution is licensed under **GPL-2.0-only** and that you
have the right to contribute it. Firmware blobs under `chips/<chip>/assets/` are not GPL:
record provenance and redistribution terms (see [FIRMWARE.md](docs/FIRMWARE.md)).
