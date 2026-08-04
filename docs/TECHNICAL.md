# For the techies

Base URL: `https://api.pmccare.in`. Auth header on every authenticated call:
`authorization: jwt <token>` — note lowercase header key and `jwt` scheme,
**not** `Authorization: Bearer`.

### `check_mobile(mobile)`
Checks whether a number is registered, before sending any OTP.

```bash
curl -s -X POST https://api.pmccare.in/authenticationConfiguration/v1/loginWithPassword \
  -H 'Content-Type: application/json' \
  -d '{"mobile":"+91XXXXXXXXXX","facebookId":null,"googleId":null,"twitterId":null}'
# -> {"code":200,"result":{"mobile":"+91XXXXXXXXXX","userState":"registered"},...}
```

### `request_otp(mobile)`
Same call for both registered and unregistered numbers.

```bash
curl -s -X POST https://api.pmccare.in/authenticationConfiguration/v1/verification \
  -H 'Content-Type: application/json' \
  -d '{"mobile":"+91XXXXXXXXXX"}'
# -> {"code":200,"result":{},"message":"generateVerfCode",...}
```

### `verify_otp(code, mobile)`
Returns the JWT in `result.token` (not a response header). Also carries the
full citizen profile (`firstName`, `emailId`, `userId`, etc.) in the same
response — we cache those alongside the token so later calls (like filing a
complaint) don't need a second lookup.

```bash
curl -s -X POST https://api.pmccare.in/authenticationConfiguration/v1/verification/verify/login \
  -H 'Content-Type: application/json' \
  -d '{"mobile":"+91XXXXXXXXXX","veriCode":"1234","fcmToken":""}'
# -> {"code":200,"result":{"token":"<JWT>","userId":"U...","userState":"registered",...}}
```

### `register(...)`
The password field is AES-128-CBC encrypted with a **hardcoded key that
doubles as the IV** (`0123456789abcdef0123456789abcdef`, same for every
install) — this isn't real encryption, but the server expects the field in
this form.

`login()` never calls this. When a number comes back `unregistered`, the
script stops and points at `REGISTRATION_URL`
(`https://www.pmccare.in/Login/enter-mobile-number/register`) instead — a
real, PMC-maintained web form on the same backend. That form is the actual
recommended path; `register()` stays here only as a documented reference for
anyone who wants to verify/use it themselves.

```bash
curl -s -X POST https://api.pmccare.in/user/v1/registerUser \
  -H 'Content-Type: application/json' \
  -d '{
    "firstName":"<NAME>","middleName":"","lastName":"",
    "gender":"<GENDER>","DOB":"<YYYY-MM-DD>","mobile":"+91XXXXXXXXXX",
    "address":"","lat":0,"long":0,"emailId":"<EMAIL>",
    "password":"<AES-CBC ciphertext, base64, hardcoded key>",
    "fcmToken":"","sourceLocation":"android","createdSource":"Device",
    "mobileDeviceToken":"","lang":"en","MUID_REG":"","channelId_REG":"",
    "EVENT_TYPE":"REG","referedBy":""
  }'
```

### `categories()` / `subcategories(id)` / `wards()` / `prabhags(ward_id)`

```bash
curl -s https://api.pmccare.in/user/v1/GrievanceCtrl/getNewCategoryList \
  -H 'authorization: jwt <JWT>'

curl -s -X POST https://api.pmccare.in/user/v1/GrievanceCtrl/getNewSubCategoryList \
  -H 'authorization: jwt <JWT>' -H 'Content-Type: application/json' \
  -d '{"categoryId":"48"}'

curl -s -X POST https://api.pmccare.in/user/v1/getWardList \
  -H 'authorization: jwt <JWT>'

curl -s -X POST https://api.pmccare.in/user/v1/GrievanceCtrl/getNewPrabhag \
  -H 'authorization: jwt <JWT>' -H 'Content-Type: application/json' \
  -d '{"wardId":"6"}'
```

### `submit_complaint(...)`

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
# -> {"code":200,"result":"PC45011","message":"Girevance added successfully"}
```

**Why `attachment.uri` is a plain URL and not an upload.** The official app
uploads photos via a separate multipart call (`POST
/objectStorage/v1/storeObject`), gets back a real PMC-hosted CDN URL — then a
confirmed bug in the app's own code discards that URL and submits a
**device-local `file://` path** instead. We verified this by pulling our own
filed complaint straight back from the server: the stored `attachment[].uri`
was that same meaningless local path, accepted with no validation at all.
Since the server evidently doesn't check this field, we skip the upload step
entirely and put a real, publicly-fetchable URL there instead — which
actually works *better* than the app's own current behavior, since ward
staff can never see the app's local-path attachments at all.

### `my_complaints()`

```bash
curl -s -X POST https://api.pmccare.in/user/v1/GrievanceCtrl/getGrievanceListByMobile \
  -H 'authorization: jwt <JWT>' -H 'Content-Type: application/json' \
  -d '{"citMobileNumber":"+91XXXXXXXXXX"}'
```

## `legacy_status.py` — a separate, older system

`complaint.pmc.gov.in` is not `api.pmccare.in` — different backend, no
account/login involved at all. It's a public token-number lookup: two calls,
no auth headers.

### `token_to_com_id(token_no)`
Resolves a token number to PMC's internal `comId` by scraping it out of the
returned HTML (`id="<comId>" name="btnTrack"` on the track button).

```bash
curl -s -X POST https://complaint.pmc.gov.in/rptTokenDetailsByTokenCitizen \
  -d 'tokenNo=WA256398&comId=&pageMode=&reopenFlag=&reopenReasonId=&reopenRemark='
```

### `track_by_com_id(com_id)`
Returns the full status and action history for a `comId`.

```bash
curl -s -X POST https://complaint.pmc.gov.in/fetchComplaintTrack \
  -H 'X-Requested-With: XMLHttpRequest' -d 'comId=617929'
```

### `check_status(token_no)`
Runs both calls in sequence and returns the status JSON directly from a
token number — this is what `report.py --check-token` calls.

### Other things worth knowing
- **Token lifetime: 180 days**, decoded from a real JWT's `iat`/`exp`. The
  identity payload itself is inside an opaque `encryptedData` blob only the
  server can read — the JWT is a pure bearer credential.
- **Uploaded photos are served with no auth at all.** `GET /image/v1/...`
  requires no token, no cookie — anyone with the URL (which embeds your
  `userId`) can view it. Treat these as public links.
- Not everything the app calls uses `api.pmccare.in` directly — the endpoint
  routing table itself is fetched at runtime from `GET
  /applicationConfig/v1/appConfiguration/getApidetails`, which is why several
  endpoint names in the bundle's static strings (e.g. the old
  `GrievanceCtrl/addGrievance`) turned out to be stale/unused — the real one
  in current traffic is `addGrievanceDirectly`.
