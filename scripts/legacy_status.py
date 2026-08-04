"""Client for the legacy PMC complaint status portal (complaint.pmc.gov.in).

This is a separate system from PMC Care (api.pmccare.in) — no login, no
token, just a public token-number lookup."""

from __future__ import annotations

import re
from typing import Any

import requests

BASE_URL = "https://complaint.pmc.gov.in"


def token_to_com_id(token_no: str) -> str | None:
    """Resolve a token number (e.g. 'WA256398') to its internal comId.

    curl -s -X POST https://complaint.pmc.gov.in/rptTokenDetailsByTokenCitizen \\
      -d 'tokenNo=WA256398&comId=&pageMode=&reopenFlag=&reopenReasonId=&reopenRemark='
    """
    r = requests.post(
        f"{BASE_URL}/rptTokenDetailsByTokenCitizen",
        data={
            "tokenNo": token_no, "comId": "", "pageMode": "",
            "reopenFlag": "", "reopenReasonId": "", "reopenRemark": "",
        },
        timeout=30,
    )
    r.raise_for_status()
    m = re.search(r'id="(\d{4,})"[^>]*name="btnTrack"|name="btnTrack"[^>]*id="(\d{4,})"', r.text)
    if not m:
        return None
    return m.group(1) or m.group(2)


def track_by_com_id(com_id: str) -> dict[str, Any]:
    """Fetch full status and history for a comId.

    curl -s -X POST https://complaint.pmc.gov.in/fetchComplaintTrack \\
      -H 'X-Requested-With: XMLHttpRequest' -d 'comId=617929'
    """
    r = requests.post(
        f"{BASE_URL}/fetchComplaintTrack",
        headers={"X-Requested-With": "XMLHttpRequest"},
        data={"comId": com_id},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def check_status(token_no: str) -> dict[str, Any]:
    """Look up a complaint's status and history by its token number."""
    com_id = token_to_com_id(token_no)
    if not com_id:
        raise ValueError(f"No complaint found for token {token_no!r}")
    return track_by_com_id(com_id)
