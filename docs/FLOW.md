# Flow diagrams

This page shows, step by step, what happens for each major action in
`pmc-care-cli`. Each diagram is a **flowchart**: boxes are steps (usually a
request sent to a PMC server), arrows show what happens next, and diamonds
are decision points where the path splits based on what the server said.
For what each request/response actually looks like, see
[TECHNICAL.md](TECHNICAL.md).

## Contents

| Section | What's there |
|---|---|
| [Login](#login-mobile--otp-only--no-password-needed) | Checking a number, sending an OTP, verifying it |
| [Registration](#registration-only-if-userstate-comes-back-unregistered) | What happens when a number has no account yet |
| [Filing a complaint](#filing-a-complaint) | Category/ward lookups through to a submitted complaint |
| [Checking status by token](#checking-status-by-token-number-no-login) | The no-login status lookup, on a separate PMC system |

---

## Login (mobile + OTP only — no password needed)

```mermaid
flowchart TD
    A[Start] --> B["POST loginWithPassword<br/>{mobile}"]
    B --> C{userState?}
    C -->|blocked| Z1["Stop — number is blocked"]
    C -->|unregistered| Z2["Stop here — go to<br/>Registration flow<br/>(no OTP wasted)"]
    C -->|registered| D["POST verification<br/>{mobile}<br/>→ OTP sent via SMS"]
    D --> E[User enters OTP code]
    E --> F["POST verification/verify/login<br/>{mobile, veriCode}<br/>→ JWT in result.token"]
    F --> H["✅ Logged in<br/>token cached ~180 days"]
```

The first step (`loginWithPassword`) is a pure lookup — it doesn't send an
OTP by itself. That's deliberate: it lets the script find out whether a
number is even registered *before* spending a real SMS on it.

## Registration (only if `userState` comes back `unregistered`)

The script deliberately does **not** try to create the account for you. There
*is* a reverse-engineered API path for it (`register()` in the client, kept
as documented reference — see [TECHNICAL.md](TECHNICAL.md)), but it was
never live-tested and it's someone's real government-services account on the
line. Instead, the moment `unregistered` shows up, the script stops and
redirects to PMC's own real registration page — same backend, a form PMC
actually maintains and validates:

```mermaid
flowchart TD
    A["login() raises NotRegisteredError"] --> B["Script prints:<br/>https://www.pmccare.in/Login/enter-mobile-number/register"]
    B --> C["User completes registration<br/>themselves, in a real browser,<br/>on PMC's own web form"]
    C --> D["User presses Enter<br/>back in the script"]
    D --> E["Script calls login() again"]
    E --> F{userState now?}
    F -->|registered| G["✅ Continue to filing a complaint"]
    F -->|still unregistered| H["Tell user to finish registering,<br/>re-run the script later"]
```

We confirmed `https://www.pmccare.in/Login/enter-mobile-number/register` is
real and live (not a guess) — its own network traffic hits the identical
`api.pmccare.in` backend, and it opens on a "नागरिक नोंदणी" (Citizen
Registration) mobile-number-and-OTP screen, matching what we found in the
app's own registration flow.

## Filing a complaint

```mermaid
flowchart TD
    A[Logged in] --> B["GET getNewCategoryList<br/>pick a category"]
    B --> C["POST getNewSubCategoryList {categoryId}<br/>pick a sub-category"]
    C --> D["POST getWardList<br/>pick a ward"]
    D --> E["POST getNewPrabhag {wardId}<br/>pick a prabhag"]
    E --> F["Host your photo yourself<br/>(S3 / Supabase / any public URL)"]
    F --> G["POST addGrievanceDirectly<br/>{category, ward, prabhag, description,<br/>lat/long, attachment: [url]}"]
    G --> H["✅ token returned e.g. PC45011"]
```

Each lookup in this chain depends on the one before it — you can't ask for
sub-categories without first picking a category, or prabhags without first
picking a ward. `report.py` walks you through all four picks as numbered
lists before making the final submit request.

## Checking status by token number (no login)

This is a separate, older PMC system (`complaint.pmc.gov.in`) — not
`api.pmccare.in`. It's a public token-number lookup: no login, no mobile
number, no OTP. Anyone with a token number can check its status.

```mermaid
flowchart TD
    A["Have a token number, e.g. WA256398"] --> B["POST rptTokenDetailsByTokenCitizen<br/>{tokenNo}<br/>→ scrape comId out of the HTML"]
    B --> C["POST fetchComplaintTrack<br/>{comId}"]
    C --> D["✅ status + full history"]
```

The first request returns a full HTML page (meant for a browser), not clean
data — the script has to pull PMC's internal complaint ID (`comId`) out of
that page's HTML before it can ask for the actual status in the second
request.
