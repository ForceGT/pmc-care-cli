# Technical reference

This document explains, endpoint by endpoint, how `pmc-care-cli` talks to
PMC's servers — written so you don't need prior experience with REST APIs to
follow it. If you already know what a POST request, JSON body, or auth
header is, skim past the primer and jump to
[The two PMC systems](#the-two-pmc-systems).

## Contents

| Section | What's there |
|---|---|
| [A quick primer](#a-quick-primer-on-what-youre-looking-at) | POST/GET, JSON, curl, headers, and tokens explained |
| [The two PMC systems](#the-two-pmc-systems) | `api.pmccare.in` vs. `complaint.pmc.gov.in` |
| [Logging in](#logging-in) | The three-step mobile + OTP login flow |
| [Registering](#registering-a-new-account) | Why we don't auto-register, and the API we found |
| [Filing a complaint](#filing-a-complaint) | Category/ward lookups and the submit call |
| [Checking status](#checking-status) | Your own complaints vs. any complaint by token |
| [Other things worth knowing](#other-things-worth-knowing) | Token lifetime, public photo URLs, and more |

---

## A quick primer on what you're looking at

Every interaction in this document follows the same shape: our script sends
a **request** to a PMC server, and the server sends back a **response**. A
few terms that'll come up constantly:

- **`POST` / `GET`** — the two kinds of requests we make. `GET` asks a
  server for information without changing anything (like checking your
  complaint list). `POST` sends data to the server, usually to create or
  change something (like logging in, or filing a complaint).
- **JSON** — the text format almost every request and response uses. It
  looks like `{"mobile": "+919028833886", "code": 5892}` — a set of
  `"key": value` pairs, wrapped in curly braces. Every example below shows
  the exact JSON sent and received.
- **`curl`** — a command-line tool for making requests, pre-installed on
  macOS and most Linux systems. Every example in this doc is a real,
  runnable `curl` command — copy one, replace the placeholder values (things
  in `<ANGLE BRACKETS>`), and run it in a terminal to see the real response
  for yourself.
- **Header** — extra metadata attached to a request, separate from the
  JSON body. In `curl`, headers are added with `-H 'Name: value'`. We use
  two: `Content-Type` (tells the server "the body is JSON") and
  `authorization` (proves who you are, once you're logged in).
- **Token / JWT** — after you log in, the server gives you a long string
  (a "JSON Web Token") that proves you're logged in. You attach it to every
  later request instead of logging in again each time — similar to how a
  website keeps you logged in with a cookie. We store this token in
  `.token_cache.json` after login.

---

## The two PMC systems

This is the single most important thing to understand before reading
further: **PMC runs two completely separate systems**, built at different
times, with no shared login or database between them.

| | `api.pmccare.in` | `complaint.pmc.gov.in` |
|---|---|---|
| What it is | The backend for the modern **PMC Care** mobile app | An older, standalone complaint portal |
| Needs login? | Yes — mobile number + OTP | No — anyone can look up any token number |
| What our code calls it | `pmccare_client.py` | `legacy_status.py` |
| Token format seen | `PC45011` (filed through the app/API) | `WA256398` (filed via WhatsApp/call center) |

Filing a complaint always goes through `api.pmccare.in` (that's the only
system with a working "create complaint" endpoint we could use safely).
Checking status can go through *either* system, depending on where the
complaint was originally filed — that's why `report.py` has two separate
status commands: `--status` (your own complaints, via `api.pmccare.in`,
needs login) and `--check-token <TOKEN>` (any complaint, via
`complaint.pmc.gov.in`, no login).

Every request below to `api.pmccare.in` needs this header once you're
logged in:

```
authorization: jwt <YOUR_TOKEN>
```

Note two things that are easy to get wrong: the header name is lowercase
`authorization`, and the value starts with the word `jwt` — **not** the more
common `Bearer` that most APIs use. If you've copied a curl example from
another project and swapped in this API's URL, this is the detail that'll
silently break it.

---

## Logging in

Logging in is three separate requests, not one. Here's why: PMC's own app
needs to know *before* sending an OTP whether your number is even
registered (so it can decide whether to show a login form or a registration
form) — so "check the number," "send the OTP," and "verify the OTP" are
three distinct steps.

### Step 1 — is this number registered?

We send your mobile number and ask PMC what it knows about it. Nothing is
texted to you yet at this step — this is a pure lookup.

```bash
curl -s -X POST https://api.pmccare.in/authenticationConfiguration/v1/loginWithPassword \
  -H 'Content-Type: application/json' \
  -d '{"mobile":"+91XXXXXXXXXX","facebookId":null,"googleId":null,"twitterId":null}'
```

The `facebookId`/`googleId`/`twitterId` fields are there because the real
app also supports social login — we always send `null` for these since
we're only using mobile+OTP.

The response tells you which of three states your number is in:

```json
{"code":200,"result":{"mobile":"+91XXXXXXXXXX","userState":"registered"},"message":"loginWithPassword",...}
```

`userState` is the field that matters — it'll be one of:
- **`"registered"`** — you have an account; continue to step 2.
- **`"unregistered"`** — no account exists yet; see
  [Registering a new account](#registering-a-new-account) below.
- **`"blocked"`** — PMC has blocked this number; nothing our script does can
  fix that.

Our code checks this *before* sending an OTP specifically so we don't waste
a real SMS on a number that isn't even registered yet.

### Step 2 — send the OTP

Only called if step 1 said `"registered"`. This texts a 4-digit code to the
phone.

```bash
curl -s -X POST https://api.pmccare.in/authenticationConfiguration/v1/verification \
  -H 'Content-Type: application/json' \
  -d '{"mobile":"+91XXXXXXXXXX"}'
```

```json
{"code":200,"result":{},"message":"generateVerfCode",...}
```

There's nothing useful in the response body here — a 200 just confirms the
SMS was sent. The code itself only exists on the recipient's phone.

### Step 3 — verify the OTP

You (or the script's `input()` prompt) type in the code you received, and
we send it back to prove you got the SMS.

```bash
curl -s -X POST https://api.pmccare.in/authenticationConfiguration/v1/verification/verify/login \
  -H 'Content-Type: application/json' \
  -d '{"mobile":"+91XXXXXXXXXX","veriCode":"1234","fcmToken":""}'
```

(`fcmToken` is a push-notification identifier the real app would normally
send — we leave it blank since we're not receiving push notifications.)

If the code matches, the response contains your login token — this is the
one and only place it appears, buried inside `result`, not in a response
header the way some APIs do it:

```json
{
  "code": 200,
  "result": {
    "token": "eyJhbGciOiJIUzI1NiIs...",
    "userId": "U38861781455196256",
    "userState": "registered",
    "firstName": "Gaurav",
    "emailId": "you@example.com",
    "...": "...many more profile fields..."
  }
}
```

Our script pulls out `token`, `userId`, `firstName`, and `emailId` from this
one response and saves them to `.token_cache.json`, so every later command
(filing a complaint, checking status) can skip straight to using the token
instead of logging in again. We decoded a real token's internal expiry
timestamp and found it's valid for **180 days** — so this cache file is
what saves you from re-entering an OTP on every single run.

---

## Registering a new account

If step 1 above came back `"unregistered"`, **our script does not try to
register you automatically.** This needs explaining, because we did figure
out how the registration API works — we just chose not to wire it up.

Here's the reasoning: we found the registration endpoint by reading the PMC
Care app's code directly (not by testing it against a real server), so we
know its *shape* but never actually confirmed it works by using it for
real. Silently running an unverified "create a government-services account"
request on your behalf, using guessed field values, felt like the wrong
default. Instead, when your number comes back unregistered, the script
prints a link to **PMC's own real registration web page** —
`https://www.pmccare.in/Login/enter-mobile-number/register` — and waits for
you to finish registering there yourself, in a browser, using PMC's actual
form. We confirmed this page is real and talks to the same `api.pmccare.in`
backend (not some other, unrelated system) by checking its network traffic.

If you still want to see (or use) the registration API we found, here it
is, documented as a reference:

```bash
curl -s -X POST https://api.pmccare.in/user/v1/registerUser \
  -H 'Content-Type: application/json' \
  -d '{
    "firstName":"<NAME>","middleName":"","lastName":"",
    "gender":"<GENDER>","DOB":"<YYYY-MM-DD>","mobile":"+91XXXXXXXXXX",
    "address":"","lat":0,"long":0,"emailId":"<EMAIL>",
    "password":"<AES-CBC ciphertext, base64, see below>",
    "fcmToken":"","sourceLocation":"android","createdSource":"Device",
    "mobileDeviceToken":"","lang":"en","MUID_REG":"","channelId_REG":"",
    "EVENT_TYPE":"REG","referedBy":""
  }'
```

**About that `password` field.** You can't just put your plain-text password
there — the app "encrypts" it first using a scheme called AES (a standard,
genuinely strong encryption algorithm — the problem isn't the algorithm,
it's how it's used here). Encryption normally needs a secret key that only
the right parties know. This app instead uses a **fixed, hardcoded key that
is baked into the app itself** — the literal string
`0123456789abcdef0123456789abcdef`, used as both the encryption key *and*
the initialization vector (a second required input for this style of
encryption). Since that string is identical in every install of the app
and we extracted it just by reading the app's code, this isn't providing
real security — anyone who has the app can produce or decrypt this
"encrypted" value. We're only doing it because the server insists the field
be shaped this way, not because it protects anything.

---

## Filing a complaint

Filing a complaint needs four pieces of information you have to actively
choose (category, sub-category, ward, prabhag), plus the complaint details
themselves. Each "which one do you mean" choice is its own lookup, and each
depends on the one before it — you can't ask for sub-categories without
first knowing which category, and so on.

### Look up the options, one step at a time

```bash
# 1. What categories exist? (e.g. "Water Supply", "Street Lights", "Road, pavement...")
curl -s https://api.pmccare.in/user/v1/GrievanceCtrl/getNewCategoryList \
  -H 'authorization: jwt <JWT>'

# 2. Given a category (categoryId 48 = "Road, pavement, divider, pits, repair..."),
#    what specific sub-categories exist? (e.g. "Repairing pothole around manhole")
curl -s -X POST https://api.pmccare.in/user/v1/GrievanceCtrl/getNewSubCategoryList \
  -H 'authorization: jwt <JWT>' -H 'Content-Type: application/json' \
  -d '{"categoryId":"48"}'

# 3. What administrative wards does PMC divide Pune into?
curl -s -X POST https://api.pmccare.in/user/v1/getWardList \
  -H 'authorization: jwt <JWT>'

# 4. Given a ward (wardId 6), what prabhags (smaller sub-areas) does it contain?
curl -s -X POST https://api.pmccare.in/user/v1/GrievanceCtrl/getNewPrabhag \
  -H 'authorization: jwt <JWT>' -H 'Content-Type: application/json' \
  -d '{"wardId":"6"}'
```

`report.py` runs all four of these for you and shows the results as
numbered lists you pick from — you never need to know the raw IDs yourself,
though the underlying requests are exactly what's shown above.

### Submit the complaint

Once you know which category/sub-category/ward/prabhag you want, this is
the request that actually creates the complaint:

```bash
curl -s -X POST https://api.pmccare.in/user/v1/GrievanceCtrl/addGrievanceDirectly \
  -H 'authorization: jwt <JWT>' -H 'Content-Type: application/json' \
  -d '{
    "userId":"<USER_ID>","citMobileNumber":"+91XXXXXXXXXX",
    "citEmail":"<EMAIL>","citFirstName":"<NAME>","citMiddleName":"NA","citLastName":"NA",
    "categoryDetailId":252,"categoryId":48,
    "wardOfficeId1":4,"gisWardName":"<WARD>",
    "prabhagId1":70,"gisPrabhagName":"<PRABHAG>",
    "pethId1":null,"gisPethName":"Select",
    "description":"<TEXT>","currentLocation":"Pune","location":"<ADDRESS>",
    "landmark":"","latitude":18.0,"longitude":73.0,
    "image":"","image1":"",
    "attachment":[{"type":"image","uri":"<YOUR PUBLIC PHOTO URL>"}],
    "applicationType":1,"startFrom":"","handleAt":"","artId":1,"startArtId":1
  }'
```

If it works, PMC hands back your complaint's tracking token directly as the
`result` value — not nested inside another object:

```json
{"code":200,"result":"PC45011","message":"Girevance added successfully"}
```

(Yes, `"Girevance"` is a typo in PMC's own server code, not ours — we're
just relaying exactly what it says.) That `PC45011` is your token — the
same kind of code you'd see in the app, and the same thing you'd give to
someone asking "what's your complaint number?"

### Why we put a plain URL in `attachment.uri` instead of uploading the photo

This part needs the most explanation, because it's not how the real app
does it, and we want to be upfront about why we diverged.

The official PMC Care app, when you attach a photo, does this in two steps:
1. It uploads the actual photo file to PMC's storage using a different
   endpoint, `POST /objectStorage/v1/storeObject`. PMC's server saves the
   image and hands back a real, working URL to it (something like
   `https://api.pmccare.in/image/v1/....jpg`).
2. It's *supposed* to then put that URL into the complaint it's filing —
   but here's the bug we found: **it doesn't.** We watched the app's own
   traffic and confirmed that after getting a valid photo URL back, the app
   throws it away and instead writes a path that only exists on your own
   phone (something like
   `file:///storage/emulated/0/Android/data/.../photo.jpg`) into the
   complaint. That path means nothing to anyone except your specific
   device — PMC's servers, or the ward engineer looking at your complaint
   later, can never open it.

We confirmed this is really happening (not a one-off glitch) by filing a
test complaint through the real app while watching its traffic, then
immediately fetching that same complaint back from PMC's server — the
stored attachment was exactly that broken, useless local file path.

Since the server clearly never checks or uses whatever string ends up in
`attachment.uri` — it happily accepted a completely unreachable local file
path with no complaint — we decided not to bother re-implementing the
two-step "upload, then (correctly) link" dance at all. Instead, if you host
your photo somewhere public yourself (any file-hosting service works — an
S3 bucket, Supabase storage, etc.) and give us that URL via
`--photo-base-url`, we put your real, working, publicly-viewable URL
straight into `attachment.uri`. It's a smaller amount of work on our end,
and — because it's an actual reachable link rather than a dead local path —
it arguably serves ward staff *better* than what the app itself currently
does.

---

## Checking status

### Your own complaints (needs login)

```bash
curl -s -X POST https://api.pmccare.in/user/v1/GrievanceCtrl/getGrievanceListByMobile \
  -H 'authorization: jwt <JWT>' -H 'Content-Type: application/json' \
  -d '{"citMobileNumber":"+91XXXXXXXXXX"}'
```

This returns every complaint tied to your mobile number, most recent first,
including its current status and full action history.

### Any complaint by token number (no login needed)

This is where `complaint.pmc.gov.in` — the *other* PMC system — comes in.
Unlike everything above, this needs no account and no OTP: if you have a
token number, PMC lets anyone look up its status.

It's two requests, because the page you'd normally type a token into
doesn't return clean data directly — it returns a full HTML web page (meant
for a browser to display), and we have to dig the actual complaint ID out
of that page first before we can ask for the real status data.

```bash
# Step 1: give PMC a token number, get back a full HTML page. Buried inside
# that HTML is PMC's internal ID for this complaint (we call it comId) —
# our code extracts it by pattern-matching the HTML text.
curl -s -X POST https://complaint.pmc.gov.in/rptTokenDetailsByTokenCitizen \
  -d 'tokenNo=WA256398&comId=&pageMode=&reopenFlag=&reopenReasonId=&reopenRemark='

# Step 2: now that we have the internal comId, ask for the actual status
# data — this one returns clean JSON, not HTML.
curl -s -X POST https://complaint.pmc.gov.in/fetchComplaintTrack \
  -H 'X-Requested-With: XMLHttpRequest' -d 'comId=617929'
```

`X-Requested-With: XMLHttpRequest` is a header that tells this particular
server "treat this like a background data request, not a page load" — it's
what makes the difference between getting back JSON versus another full
HTML page.

The response from step 2 includes the complaint's description, category,
current status, and a full timeline of who it's been assigned to and when:

```json
{
  "complaintMaster": {
    "tokenNo": "WA256398",
    "isResolved": null,
    "description": "Dear PMC, please address this civic issue...",
    "...": "..."
  },
  "lstTrack": [
    {"date": "30/07/2026 01:37:33 PM", "action": "Assigned", "...": "..."},
    {"date": "30/07/2026 04:51:38 PM", "action": "InProcess", "...": "..."}
  ]
}
```

`isResolved` is worth knowing about: it's `null` while the complaint is
still open, `"Y"` when resolved, `"R"` when rejected.

Our `report.py --check-token <TOKEN>` command runs both of these requests
for you in sequence and prints the final JSON.

---

## Other things worth knowing

- **Your login token lasts 180 days.** We figured this out by decoding a
  real token — a JWT secretly contains an expiry timestamp inside it, not
  just a random string. The part of the token that identifies *you*
  specifically is further encrypted inside an opaque blob that only PMC's
  server can read — so even though we can see when the token expires, we
  can't see who it belongs to just by looking at it.
- **Photos you (or the app) upload to PMC are public, with no login
  required to view them.** `GET /image/v1/...` — the endpoint that serves
  uploaded images — doesn't check for any token or cookie. Anyone who has
  (or guesses) the URL can view the photo. The URL does embed your PMC user
  ID, so it's not easily guessable, but treat any such URL as a public
  link, not a private one.
- **The app doesn't hardcode most of its own API paths.** Instead, it asks
  PMC's server for a list of current endpoint paths at startup, via `GET
  /applicationConfig/v1/appConfiguration/getApidetails`. This explains a
  discrepancy we ran into early on: some endpoint names we found by reading
  the app's installed code directly (like an old path called
  `GrievanceCtrl/addGrievance`) turned out to be stale and no longer used —
  the real, currently-live endpoint is `addGrievanceDirectly`, which we only
  found by watching real network traffic rather than trusting the
  installed code alone.
