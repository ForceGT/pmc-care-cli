---
description: Report a folder of pothole photos to PMC Care, one by one, under your own login.
argument-hint: [path-to-photos-folder]
---

You are helping the user file civic complaints about potholes they personally
photographed, to the Pune Municipal Corporation's PMC Care system, under the
user's **own** citizen account. This is ordinary citizen use — one real issue,
one real photo, one complaint, with the user confirming each submission.

## Guardrails (do not skip)
- Only ever authenticate with the user's own credentials from `.env`. Never use
  credentials extracted from the app binary.
- One complaint per genuine pothole. Do not fabricate, duplicate, or bulk-fire
  reports. The per-photo confirmation prompt stays on unless the user explicitly
  passes `--yes` for a batch they've already eyeballed.
- If the user asks to report issues that aren't theirs to report, or to submit
  on behalf of many identities, stop and say that's outside this tool's purpose.

## Steps
1. Ensure `.env` exists (copy from `.env.example` and have the user fill in
   `PMCCARE_MOBILE` / `PMCCARE_PASSWORD`). Never print the filled-in values.
2. Confirm dependencies: `pip install requests pillow`.
3. Run the reporter against the folder in `$ARGUMENTS` (default: ask the user):
   ```
   python scripts/report.py --dir "$ARGUMENTS"
   ```
   Add `--debug` on the first run to confirm the request/response shapes, then
   fix any field names in `scripts/pmccare_client.py` (the `FIELDS`/`HEADERS`
   maps) if the live API disagrees.
4. Report back the tokens returned for each filed complaint.
5. To check status later: `python scripts/report.py --status`.

## Note on field names
Endpoint paths are confirmed from the app; JSON field names are a best-effort
reconstruction centralized in `FIELDS`/`HEADERS`. The first real login + submit
(run with `--debug`) tells you the true shape — adjust those two maps once and
everything else follows.
