#!/usr/bin/env python3
"""One-time setup: write .env with your PMC Care mobile number."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def prompt_mobile() -> str:
    """Prompt until a 10-digit mobile number is entered, and return it."""
    while True:
        raw = input("Mobile number registered with PMC Care (10 digits): ").strip()
        digits = re.sub(r"\D", "", raw)
        if len(digits) == 10:
            return digits
        print("  That doesn't look like a 10-digit number, try again.")


def main() -> int:
    """Prompt for a mobile number and write .env."""
    if ENV_PATH.exists():
        overwrite = input(f"{ENV_PATH} already exists. Overwrite? [y/N] ").strip().lower()
        if overwrite != "y":
            print("Left .env unchanged.")
            return 0

    mobile = prompt_mobile()
    ENV_PATH.write_text(
        f'PMCCARE_MOBILE="{mobile}"\n'
        f'PMCCARE_USE_OTP="1"\n'
        f'PMCCARE_BASE_URL="https://api.pmccare.in"\n'
    )
    print(f"Wrote {ENV_PATH}. You're ready to run scripts/report.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
