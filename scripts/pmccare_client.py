"""Client for the PMC Care API (api.pmccare.in)."""

from __future__ import annotations

import base64
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding as sympadding
    _HAVE_CRYPTO = True
except ImportError:
    _HAVE_CRYPTO = False


BASE_URL_DEFAULT = "https://api.pmccare.in"
TOKEN_CACHE_PATH = Path(__file__).resolve().parent.parent / ".token_cache.json"
REGISTRATION_URL = "https://www.pmccare.in/Login/enter-mobile-number/register"

_REGISTER_PW_KEY_HEX = "0123456789abcdef0123456789abcdef"


class NotRegisteredError(RuntimeError):
    """Raised when the mobile number has no PMC Care account."""
    def __init__(self, mobile: str):
        super().__init__(
            f"{mobile} is not registered with PMC Care yet.\n"
            f"Register at: {REGISTRATION_URL}\n"
            f"then re-run this script.")
        self.mobile = mobile
        self.registration_url = REGISTRATION_URL


@dataclass
class Config:
    base_url: str
    mobile: str
    use_otp: bool
    debug: bool = False

    @classmethod
    def from_env(cls, debug: bool = False) -> "Config":
        """Build a Config from PMCCARE_* environment variables."""
        return cls(
            base_url=os.environ.get("PMCCARE_BASE_URL", BASE_URL_DEFAULT).rstrip("/"),
            mobile=os.environ.get("PMCCARE_MOBILE", ""),
            use_otp=os.environ.get("PMCCARE_USE_OTP", "1") == "1",
            debug=debug,
        )


class PMCCareClient:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.session = requests.Session()
        self.token: str | None = None
        self.user_id: str | None = None
        self.first_name: str = ""
        self.email: str = ""

    def _headers(self, authed: bool = False) -> dict[str, str]:
        """Build request headers; adds the auth header if authed=True."""
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if authed:
            if not self.token:
                raise RuntimeError("Not logged in — call login() first.")
            h["authorization"] = f"jwt {self.token}"
        return h

    def _post(self, path: str, body: dict[str, Any], authed: bool = False) -> dict:
        """POST JSON to path and return the parsed response."""
        url = f"{self.cfg.base_url}/{path.lstrip('/')}"
        if self.cfg.debug:
            print(f"\n--> POST {url}\n    body={_redact(body)}", file=sys.stderr)
        r = self.session.post(url, headers=self._headers(authed), json=body, timeout=30)
        if self.cfg.debug:
            print(f"<-- {r.status_code} {r.text[:800]}", file=sys.stderr)
        r.raise_for_status()
        return r.json()

    def _get(self, path: str, authed: bool = False) -> dict:
        """GET path and return the parsed response."""
        url = f"{self.cfg.base_url}/{path.lstrip('/')}"
        r = self.session.get(url, headers=self._headers(authed), timeout=30)
        if self.cfg.debug:
            print(f"<-- GET {url} {r.status_code}", file=sys.stderr)
        r.raise_for_status()
        return r.json()

    def check_mobile(self, mobile: str | None = None) -> str:
        """Return userState for a mobile number: 'registered' | 'unregistered' | 'blocked'.

        curl -s -X POST https://api.pmccare.in/authenticationConfiguration/v1/loginWithPassword \\
          -H 'Content-Type: application/json' \\
          -d '{"mobile":"+91XXXXXXXXXX","facebookId":null,"googleId":null,"twitterId":null}'
        """
        mobile = mobile or self.cfg.mobile
        resp = self._post("authenticationConfiguration/v1/loginWithPassword", {
            "mobile": mobile, "facebookId": None, "googleId": None, "twitterId": None,
        })
        return resp["result"]["userState"]

    def request_otp(self, mobile: str | None = None) -> dict:
        """Send an OTP SMS to mobile.

        curl -s -X POST https://api.pmccare.in/authenticationConfiguration/v1/verification \\
          -H 'Content-Type: application/json' \\
          -d '{"mobile":"+91XXXXXXXXXX"}'
        """
        mobile = mobile or self.cfg.mobile
        return self._post("authenticationConfiguration/v1/verification", {"mobile": mobile})

    def verify_otp(self, code: str, mobile: str | None = None, fcm_token: str = "") -> dict:
        """Verify the OTP code, store the resulting token/profile, and return the profile.

        curl -s -X POST https://api.pmccare.in/authenticationConfiguration/v1/verification/verify/login \\
          -H 'Content-Type: application/json' \\
          -d '{"mobile":"+91XXXXXXXXXX","veriCode":"1234","fcmToken":""}'
        """
        mobile = mobile or self.cfg.mobile
        resp = self._post("authenticationConfiguration/v1/verification/verify/login", {
            "mobile": mobile, "veriCode": code.strip(), "fcmToken": fcm_token,
        })
        result = resp["result"]
        if result.get("token"):
            self.token = result["token"]
            self.user_id = result.get("userId")
            self.first_name = result.get("firstName", "")
            self.email = result.get("emailId", "")
        _cache_token(mobile, self.token, self.user_id, self.first_name, self.email)
        return result

    def login(self, otp_prompt=None) -> str:
        """Log in using a cached token if available, otherwise run the OTP flow.
        Raises NotRegisteredError if the mobile number has no account."""
        cached = _load_cached_token(self.cfg.mobile)
        if cached:
            self.token, self.user_id, self.first_name, self.email = cached
            return "registered"

        state = self.check_mobile()
        if state == "blocked":
            raise RuntimeError(f"Mobile {self.cfg.mobile} is blocked by PMC Care.")
        if state == "unregistered":
            raise NotRegisteredError(self.cfg.mobile)

        self.request_otp()
        prompt = otp_prompt or (lambda: input(f"Enter the OTP sent to {self.cfg.mobile}: "))
        result = self.verify_otp(str(prompt()))
        return result.get("userState", state)

    def register(self, *, first_name: str, mobile: str, email: str, password: str,
                dob: str, gender: str, middle_name: str = "", last_name: str = "",
                address: str = "", lat: float = 0.0, lon: float = 0.0,
                referred_by: str = "", lang: str = "en") -> dict:
        """Create a new PMC Care account. Requires an OTP already verified for
        mobile via verify_otp(). Not called by login().

        curl -s -X POST https://api.pmccare.in/user/v1/registerUser \\
          -H 'Content-Type: application/json' \\
          -d '{
            "firstName":"<NAME>","middleName":"","lastName":"",
            "gender":"<GENDER>","DOB":"<YYYY-MM-DD>","mobile":"+91XXXXXXXXXX",
            "address":"","lat":0,"long":0,"emailId":"<EMAIL>",
            "password":"<AES-CBC ciphertext, base64>",
            "fcmToken":"","sourceLocation":"android","createdSource":"Device",
            "mobileDeviceToken":"","lang":"en","MUID_REG":"","channelId_REG":"",
            "EVENT_TYPE":"REG","referedBy":""
          }'
        """
        body = {
            "firstName": first_name, "middleName": middle_name, "lastName": last_name,
            "gender": gender, "DOB": dob, "mobile": mobile, "address": address,
            "lat": lat, "long": lon, "emailId": email,
            "password": _encrypt_password_legacy(password),
            "fcmToken": "",
            "sourceLocation": "android",
            "createdSource": "Device",
            "mobileDeviceToken": "",
            "lang": lang,
            "MUID_REG": "",
            "channelId_REG": "",
            "EVENT_TYPE": "REG",
            "referedBy": referred_by,
        }
        resp = self._post("user/v1/registerUser", body)
        result = resp.get("result", {})
        if isinstance(result, dict) and result.get("token"):
            self.token = result["token"]
            self.user_id = result.get("userId")
            self.first_name = first_name
            self.email = email
            _cache_token(mobile, self.token, self.user_id, self.first_name, self.email)
        return resp

    def categories(self) -> dict:
        """List complaint categories.

        curl -s https://api.pmccare.in/user/v1/GrievanceCtrl/getNewCategoryList \\
          -H 'authorization: jwt <JWT>'
        """
        return self._get("user/v1/GrievanceCtrl/getNewCategoryList", authed=True)

    def subcategories(self, category_id: str) -> dict:
        """List sub-categories for a category.

        curl -s -X POST https://api.pmccare.in/user/v1/GrievanceCtrl/getNewSubCategoryList \\
          -H 'authorization: jwt <JWT>' -H 'Content-Type: application/json' \\
          -d '{"categoryId":"48"}'
        """
        return self._post("user/v1/GrievanceCtrl/getNewSubCategoryList",
                          {"categoryId": str(category_id)}, authed=True)

    def wards(self) -> dict:
        """List wards.

        curl -s -X POST https://api.pmccare.in/user/v1/getWardList \\
          -H 'authorization: jwt <JWT>'
        """
        return self._post("user/v1/getWardList", {}, authed=True)

    def prabhags(self, ward_id: str) -> dict:
        """List prabhags for a ward.

        curl -s -X POST https://api.pmccare.in/user/v1/GrievanceCtrl/getNewPrabhag \\
          -H 'authorization: jwt <JWT>' -H 'Content-Type: application/json' \\
          -d '{"wardId":"6"}'
        """
        return self._post("user/v1/GrievanceCtrl/getNewPrabhag",
                          {"wardId": str(ward_id)}, authed=True)

    def submit_complaint(self, *, description: str, latitude: float, longitude: float,
                          location: str, category_id: int, category_detail_id: int,
                          ward_office_id: int, gis_ward_name: str,
                          prabhag_id: int, gis_prabhag_name: str,
                          citizen_first_name: str, citizen_email: str,
                          image_url: str | None = None, landmark: str = "") -> dict:
        """File a complaint. image_url should be a public URL to a photo you host.

        curl -s -X POST https://api.pmccare.in/user/v1/GrievanceCtrl/addGrievanceDirectly \\
          -H 'authorization: jwt <JWT>' -H 'Content-Type: application/json' \\
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
            "attachment":[{"type":"image","uri":"<PHOTO URL>"}],
            "applicationType":1,"startFrom":"","handleAt":"","artId":1,"startArtId":1
          }'
        """
        if not self.user_id:
            raise RuntimeError("Not logged in — call login() first.")
        body = {
            "userId": self.user_id,
            "citMobileNumber": self.cfg.mobile,
            "citEmail": citizen_email,
            "citFirstName": citizen_first_name, "citMiddleName": "NA", "citLastName": "NA",
            "categoryDetailId": category_detail_id, "categoryId": category_id,
            "wardOfficeId1": ward_office_id, "gisWardName": gis_ward_name, "gisWardName_mar": "",
            "prabhagId1": prabhag_id, "gisPrabhagName": gis_prabhag_name, "gisPrabhagName_mar": "",
            "pethId1": None, "gisPethName": "Select", "gisPethName_mar": "", "gisBPPethNo": "",
            "description": description, "currentLocation": "Pune", "location": location,
            "landmark": landmark, "latitude": latitude, "longitude": longitude,
            "image": "", "image1": "",
            "attachment": [{"type": "image", "uri": image_url}] if image_url else [],
            "applicationType": 1, "startFrom": "", "handleAt": "",
            "artId": 1, "startArtId": 1,
        }
        return self._post("user/v1/GrievanceCtrl/addGrievanceDirectly", body, authed=True)

    def my_complaints(self) -> dict:
        """List complaints filed under the logged-in mobile number.

        curl -s -X POST https://api.pmccare.in/user/v1/GrievanceCtrl/getGrievanceListByMobile \\
          -H 'authorization: jwt <JWT>' -H 'Content-Type: application/json' \\
          -d '{"citMobileNumber":"+91XXXXXXXXXX"}'
        """
        return self._post("user/v1/GrievanceCtrl/getGrievanceListByMobile",
                          {"citMobileNumber": self.cfg.mobile}, authed=True)


def _cache_token(mobile: str, token: str | None, user_id: str | None,
                  first_name: str = "", email: str = "") -> None:
    """Write the token and profile to the local cache file."""
    if not token:
        return
    TOKEN_CACHE_PATH.write_text(json.dumps({
        "mobile": mobile, "token": token, "user_id": user_id,
        "first_name": first_name, "email": email, "cached_at": time.time(),
    }))


def _load_cached_token(mobile: str) -> tuple[str, str, str, str] | None:
    """Read a still-valid cached token for mobile, or None."""
    if not TOKEN_CACHE_PATH.exists():
        return None
    try:
        data = json.loads(TOKEN_CACHE_PATH.read_text())
    except (ValueError, OSError):
        return None
    if data.get("mobile") != mobile or not data.get("token"):
        return None
    if time.time() - data.get("cached_at", 0) > (179 * 86400):
        return None
    return data["token"], data.get("user_id"), data.get("first_name", ""), data.get("email", "")


def _encrypt_password_legacy(password: str) -> str:
    """Encrypt a password with AES-128-CBC for the registerUser payload."""
    if not _HAVE_CRYPTO:
        raise RuntimeError("pip install cryptography")
    key = bytes.fromhex(_REGISTER_PW_KEY_HEX)
    padder = sympadding.PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(password.encode()) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.CBC(key))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(ciphertext).decode()


def _redact(obj: Any) -> Any:
    """Return a copy of obj with secret-looking values masked."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            lk = k.lower()
            if any(s in lk for s in ("password", "token", "otp", "vericode")):
                out[k] = "***"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(obj, list):
        return [_redact(x) for x in obj]
    return obj
