# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Python CLI that files civic complaints (potholes, by default) to **PMC Care**
(`api.pmccare.in`), the Pune Municipal Corporation's citizen-services app, and
checks complaint status. It logs in as the real user (OTP, their own mobile
number) and files complaints under their own account — it does not use any
credential extracted from the app, and does not touch other people's accounts.

There is no build step, no test suite, and no linter configured. This is a
small, dependency-light script-based project (`requests`, `pillow`,
`cryptography` — see `requirements.txt`).

## Commands

```bash
pip install -r requirements.txt   # install dependencies
python scripts/init.py            # one-time setup: writes .env with the user's mobile number
python scripts/report.py --status                    # log in, list filed complaints
python scripts/report.py --check-token WA256398       # no-login status lookup (legacy_status.py)
python scripts/report.py --dir <folder> --photo-base-url <url>   # file complaints from a folder of photos
python scripts/report.py --dir <folder> --photo-base-url <url> --yes   # skip per-photo confirmation
python scripts/report.py --dir ... --debug            # print every request/response (secrets redacted)
python3 -m py_compile scripts/*.py   # the closest thing to a build check — no test suite exists
```

`scripts/report.py` refuses to run without a `.env` file (created by
`scripts/init.py`) containing `PMCCARE_MOBILE`; it exits with a message
pointing at `init.py` rather than failing silently.

## Architecture

**Two entirely separate PMC backends, with no shared login or database.**
This split runs through the whole codebase and is the most important thing
to understand before changing anything:

- `scripts/pmccare_client.py` (`PMCCareClient`) talks to **`api.pmccare.in`**
  — the modern PMC Care app's backend. Everything requiring login (check
  mobile, OTP, filing a complaint, listing your own complaints) goes through
  here. Auth header is `authorization: jwt <token>` — lowercase key, `jwt`
  scheme, not the more common `Bearer`.
- `scripts/legacy_status.py` talks to **`complaint.pmc.gov.in`** — an older,
  independent complaint portal. No login: a public token-number lookup
  (`token_to_com_id` scrapes an internal ID out of returned HTML, then
  `track_by_com_id` fetches the actual status JSON). This is what
  `report.py --check-token` uses.
- `scripts/report.py` is the CLI entry point that wires both clients into
  `argparse` subcommands/flags and drives the interactive prompts
  (category → sub-category → ward → prabhag selection, OTP entry, per-photo
  submit confirmation).
- `scripts/init.py` is a one-time setup script — it prompts for a mobile
  number and writes `.env`. It does not read or use any other config.

**Login flow** (`PMCCareClient.login()`): tries a cached token from
`.token_cache.json` first (valid ~180 days, per a real decoded JWT's
`iat`/`exp`); if none, calls `check_mobile()` — a pure lookup that must
happen *before* sending an OTP, since `unregistered`/`blocked` numbers
shouldn't get one. Only `registered` numbers proceed to `request_otp()` →
`verify_otp()`. If `unregistered`, `login()` raises `NotRegisteredError`
rather than attempting registration — `PMCCareClient.register()` exists
(with a real, working payload shape, including the AES-128-CBC "encryption"
of the password field using a hardcoded key baked into the app) but is
**deliberately never called by `login()`**. Instead, unregistered users are
pointed at PMC's own real registration web page
(`REGISTRATION_URL`), because `register()`'s payload was reverse-engineered
from the app's code and never live-tested — don't wire it into the main
flow without that being a deliberate, discussed decision.

**Filing a complaint** (`submit_complaint()` / `POST
.../GrievanceCtrl/addGrievanceDirectly`): category, sub-category, ward, and
prabhag are each separate, sequentially-dependent lookups
(`categories()` → `subcategories(id)` → `wards()` → `prabhags(ward_id)`);
`report.py`'s `resolve_category_chain()` walks the user through picking one
of each as a numbered list, once per run, and reuses that same selection for
every photo in a `--dir` batch (see "Known limitations" in `README.md` for
why that's a real gap if a batch spans multiple wards).

**Photo attachment is a plain URL, not an upload.** The real app uploads via
`POST /objectStorage/v1/storeObject`, gets back a working PMC-hosted CDN URL,
then (confirmed bug) discards it and submits a device-local `file://` path
instead — which the server accepts without validation. This codebase
deliberately does not replicate that upload step: `report.py`'s
`--photo-base-url` flag assumes the user already hosts their photos
somewhere public, and the URL is passed straight into
`attachment.uri` in the complaint payload.

**Every endpoint's docstring in `pmccare_client.py` and `legacy_status.py`
includes the exact curl command for that call** — when adding or changing an
endpoint, keep that pattern (docstring + runnable curl example), matching
what's documented in `docs/TECHNICAL.md`.

## Repo layout

- `scripts/` — all runtime code. `frida_ssl_bypass.js` and
  `mitm_intercept_submit.py` are investigation-only tooling used to discover
  these endpoints, not part of the shipped CLI — they're gitignored and
  should stay that way.
- `docs/FLOW.md` — Mermaid flowcharts of the login, registration, filing, and
  status-check flows.
- `docs/TECHNICAL.md` — endpoint-by-endpoint reference with curl examples,
  written for readers with no prior REST API experience.
- `README.md` — user-facing getting-started guide with real example
  transcripts; "Getting started" steps are collapsed into `<details>` blocks.
  Keep the "Known limitations" section current — it documents real,
  intentional gaps (raw-coordinate `location` instead of a geocoded address;
  one category/ward chain applied to an entire photo batch).

## Working in this repo

- `.env` (real mobile number) and `.token_cache.json` (a live JWT, ~180-day
  lifetime) must never be committed — both are gitignored; don't remove those
  rules.
- Any new field name, endpoint path, or payload shape must come from a real,
  verified response — this project's credibility rests on every documented
  behavior being something that was actually observed working, not guessed
  from convention. If you're not sure a shape is real, say so explicitly
  rather than presenting it as confirmed (see how `register()` is flagged as
  unverified, both in code comments and in `docs/TECHNICAL.md`).
