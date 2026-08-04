# PMC Care CLI

## What this project does

A small Python CLI to file civic complaints (potholes, by default) to **PMC
Care** (`api.pmccare.in`), the Pune Municipal Corporation's citizen-services
app — scripted, so you can walk through a day's worth of pothole photos and
report them one by one instead of doing it by hand in the app.

It logs in as **you** (OTP, your own mobile number) and files complaints
under **your own account** — same as if you'd used the app yourself, just
batched. It does not use any credential extracted from the app, does not
touch anyone else's account, and does not silently bulk-submit — each photo
is confirmed before it's sent unless you explicitly pass `--yes`.

Every endpoint and payload shape used here was either captured from our own
decrypted device traffic (Frida + mitmproxy, on our own login) or read
directly out of the app's decompiled bytecode. Nothing here is guessed from
public documentation — PMC Care doesn't publish any.

---

## Getting started

### 1. Install

```bash
git clone https://github.com/ForceGT/pmc-care-cli
cd pmc-care-cli
pip install requests pillow cryptography
```

### 2. Configure your mobile number

```bash
cp .env.example .env
```

Edit `.env`:

```
PMCCARE_MOBILE="9028833886"
PMCCARE_USE_OTP="1"
PMCCARE_BASE_URL="https://api.pmccare.in"
```

That's the only thing you need to set — there's no password to configure,
OTP is the only login method.

### 3. First login

Any command that talks to PMC Care logs you in automatically the first time:

```
$ python scripts/report.py --status
Logging in as 9028833886 ...
Enter the OTP sent to 9028833886: 5892
Logged in.
[
  {
    "tokenNo": "PC45011",
    "grievanceStatus": "InProcess",
    ...
  }
]
```

A real OTP is texted to your phone — type it in and press Enter. The
resulting login token is cached in `.token_cache.json` for ~180 days, so you
won't be asked for OTP again until it expires.

### 4. If you're not registered yet

If PMC Care doesn't recognize your number, the script stops and tells you
where to register instead of guessing at an account-creation API on your
behalf:

```
$ python scripts/report.py --status
Logging in as 9028833886 ...

9028833886 is not registered with PMC Care yet.
Register at: https://www.pmccare.in/Login/enter-mobile-number/register
then re-run this script.

Press Enter once you've finished registering there (Ctrl+C to quit)...
```

Open that link in a browser, complete registration there (a real PMC form —
mobile + OTP, then your name/email/etc.), then come back and press Enter.
The script logs in again automatically.

### 5. Check the status of an existing complaint (no login needed)

If you already have a token number — from the app, from a WhatsApp/call-center
complaint, or from a previous run of this script — you can check its status
without logging in at all:

```
$ python scripts/report.py --check-token WA256398
{
  "complaintMaster": {
    "tokenNo": "WA256398",
    "isResolved": null,
    "description": "Dear PMC, please address this civic issue...",
    ...
  },
  "lstTrack": [
    {"date": "30/07/2026 01:37:33 PM", "action": "Assigned", ...},
    {"date": "30/07/2026 04:51:38 PM", "action": "InProcess", ...}
  ]
}
```

This hits a completely different, older PMC system (`complaint.pmc.gov.in`)
— see [FLOW.md](docs/FLOW.md) for why.

### 6. File a single complaint

Put one photo in a folder, then run:

```
$ python scripts/report.py --dir ~/potholes/2026-08-05 \
    --photo-base-url https://your-bucket.example.com/potholes \
    --description "Deep pothole causing two-wheelers to swerve into traffic"
Logging in as 9028833886 ...
Logged in.
Found 1 photo(s).

Category:
  1. Bhavan
  2. Birth And Death
  ...
  22. Road, pavement, divider, pits, repair / new speed breaker / zebra crossing
  ...
  34. Water Supply
Pick 1-34: 22

Sub-category:
  1. Repair/re-sufacing of roads/footpaths
  2. Stop line at Signal before Zebra Crossing
  3. Others road
  4. Making/Repairing/Removal Speedbreaker
  5. Marking of Parking Line
  6. Repairing pothole around manhole
  ...
Pick 1-11: 1

Ward:
  1. Aundh - Baner
  2. Kasba Peth
  3. Bibwewadi
  ...
Pick 1-16: 3

Prabhag:
  1. 19 Padmavati - Parvati Darshan
  2. 20 Shankar Maharaj Math - Bibvewadi
  ...
Pick 1-4: 2

[1/1] IMG_20260805_091423.jpg
    location : 18.472679, 73.845221 (EXIF)
    text     : Deep pothole causing two-wheelers to swerve into traffic
    photo url: https://your-bucket.example.com/potholes/IMG_20260805_091423.jpg
    submit this complaint? [y/N] y
    submitted -> PC45012

Done. Filed 1 complaint(s):
  IMG_20260805_091423.jpg -> PC45012
```

Note the `--photo-base-url` requirement: the script doesn't upload your photo
anywhere — it assumes you've already put it somewhere public (any
bucket/CDN works), and just tells PMC that URL. See
[TECHNICAL.md](docs/TECHNICAL.md) for why that's enough.

If a photo has no GPS in its EXIF data, the script asks you to type
`lat,lon` manually, or press Enter to skip that photo.

### 7. File complaints in bulk

Put a whole day's photos in one folder and run the same command — the
script walks you through every photo one at a time, reusing the same
category/ward/prabhag picked at the start:

```
$ python scripts/report.py --dir ~/potholes/2026-08-05 \
    --photo-base-url https://your-bucket.example.com/potholes
...
Found 6 photo(s).

Category: ...
Pick 1-34: 22
Sub-category: ...
Pick 1-11: 1
Ward: ...
Pick 1-16: 3
Prabhag: ...
Pick 1-4: 2

[1/6] IMG_20260805_091423.jpg
    location : 18.472679, 73.845221 (EXIF)
    text     : Pothole on the road, please repair.
    photo url: https://your-bucket.example.com/potholes/IMG_20260805_091423.jpg
    submit this complaint? [y/N] y
    submitted -> PC45012

[2/6] IMG_20260805_093011.jpg
    location : 18.473112, 73.846903 (EXIF)
    text     : Pothole on the road, please repair.
    photo url: https://your-bucket.example.com/potholes/IMG_20260805_093011.jpg
    submit this complaint? [y/N] n
    skipped.

[3/6] IMG_20260805_094502.jpg
    location : 18.471950, 73.844410 (EXIF)
    text     : Pothole on the road, please repair.
    photo url: https://your-bucket.example.com/potholes/IMG_20260805_094502.jpg
    submit this complaint? [y/N] y
    submitted -> PC45013
...
Done. Filed 4 complaint(s):
  IMG_20260805_091423.jpg -> PC45012
  IMG_20260805_094502.jpg -> PC45013
  IMG_20260805_101233.jpg -> PC45014
  IMG_20260805_104501.jpg -> PC45015
```

See "Known limitations" below if your day's photos span more than one ward.

Add `--yes` to skip the "submit this complaint?" prompt for every photo —
useful once you've reviewed the batch and trust it:

```bash
python scripts/report.py --dir ~/potholes/2026-08-05 \
    --photo-base-url https://your-bucket.example.com/potholes --yes
```

### 8. Check everything you've filed

```
$ python scripts/report.py --status
Logging in as 9028833886 ...
Logged in.
[
  {"tokenNo": "PC45011", "grievanceStatus": "InProcess", ...},
  {"tokenNo": "PC45012", "grievanceStatus": "Resolved", ...}
]
```

### Debugging

Add `--debug` to any command to print every request and response (secrets
like your token/OTP are redacted):

```bash
python scripts/report.py --status --debug
```

---

For the full request/response flow diagrams (login, registration, filing,
status-check), see [FLOW.md](docs/FLOW.md).

For an endpoint-by-endpoint breakdown with curl examples, see
[TECHNICAL.md](docs/TECHNICAL.md).

---

## Known limitations

- **`location` is raw coordinates, not a real address.** The script submits
  the literal EXIF coordinates as a string (`"18.472679,73.845221"`). The
  real PMC Care app reverse-geocodes GPS into a street address before
  submitting; this script doesn't, so every complaint you file shows a
  coordinate pair where PMC's UI normally shows an address.
- **One category/sub-category/ward/prabhag for the whole batch.** The
  category chain is picked once before the photo loop and reused for every
  photo in `--dir`. If a day's photos span more than one ward, this version
  has no way to assign them differently — they'll all get filed under
  whatever was picked first.
