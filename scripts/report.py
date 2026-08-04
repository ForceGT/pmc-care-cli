#!/usr/bin/env python3
"""Report pothole photos to PMC Care, one by one."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from pmccare_client import PMCCareClient, Config, NotRegisteredError

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".webp"}


def load_dotenv(path: Path) -> None:
    """Load KEY=VALUE lines from path into os.environ."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def exif_gps(path: Path) -> tuple[float, float] | None:
    """Return (lat, lon) read from a photo's EXIF data, or None."""
    try:
        from PIL import Image, ExifTags
    except ImportError:
        return None
    try:
        img = Image.open(path)
        exif = img._getexif() or {}
    except Exception:
        return None
    gps_ifd = None
    for tag, val in exif.items():
        if ExifTags.TAGS.get(tag) == "GPSInfo":
            gps_ifd = val
    if not gps_ifd:
        return None
    g = {ExifTags.GPSTAGS.get(k, k): v for k, v in gps_ifd.items()}

    def _dms(dms, ref):
        d, m, s = (float(x) for x in dms)
        val = d + m / 60 + s / 3600
        return -val if ref in ("S", "W") else val

    try:
        lat = _dms(g["GPSLatitude"], g.get("GPSLatitudeRef", "N"))
        lon = _dms(g["GPSLongitude"], g.get("GPSLongitudeRef", "E"))
        return lat, lon
    except Exception:
        return None


def pick_from_list(label: str, items: list[tuple[str, str]]) -> str:
    """Prompt the user to pick one of items (id, display_name) and return its id."""
    print(f"\n{label}:")
    for i, (_id, name) in enumerate(items, 1):
        print(f"  {i}. {name}")
    while True:
        raw = input(f"Pick 1-{len(items)}: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(items):
            return items[int(raw) - 1][0]


def resolve_category_chain(client: PMCCareClient) -> dict:
    """Prompt the user through category -> sub-category -> ward -> prabhag."""
    cats = client.categories()["result"]["lstCategory"]
    cat_id = pick_from_list("Category", [(str(c["ccmId"]), c["ccmName"]) for c in cats])

    subs = client.subcategories(cat_id)["result"]["lstCategoryDetails"]
    sub_id = pick_from_list("Sub-category", [(str(s["ccdId"]), s["ccdName"]) for s in subs])

    wards = client.wards()["result"]
    seen = {}
    for w in wards:
        seen[w["wardId"]] = w["wardName"]
    ward_id = pick_from_list("Ward", [(str(k), v) for k, v in seen.items()])
    ward_name = seen[int(ward_id)]

    prabhags = client.prabhags(ward_id)["result"]["lstPrabhag"]
    prm_id = pick_from_list("Prabhag", [(str(p["prmId"]), p["prmName"]) for p in prabhags])
    prm_name = next(p["prmName"] for p in prabhags if str(p["prmId"]) == prm_id)

    return {
        "category_id": int(cat_id), "category_detail_id": int(sub_id),
        "ward_office_id": int(ward_id), "gis_ward_name": ward_name,
        "prabhag_id": int(prm_id), "gis_prabhag_name": prm_name,
    }


def main() -> int:
    """Parse args, log in, and report photos or print status."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", help="folder of pothole photos to report")
    ap.add_argument("--description", default="Pothole on the road, please repair.")
    ap.add_argument("--photo-base-url", help="public base URL where --dir's photos are"
                     " also hosted (e.g. https://your-bucket.example.com/potholes/) "
                     "— filename is appended. Required to attach a photo.")
    ap.add_argument("--yes", action="store_true", help="don't ask before each submit")
    ap.add_argument("--status", action="store_true", help="list your complaints and exit")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    cfg = Config.from_env(debug=args.debug)
    if not cfg.mobile:
        print("Fill PMCCARE_MOBILE in .env first (copy from .env.example).", file=sys.stderr)
        return 2

    client = PMCCareClient(cfg)
    print(f"Logging in as {cfg.mobile} ...")
    try:
        state = client.login()
    except NotRegisteredError as e:
        print(f"\n{e}\n", file=sys.stderr)
        input("Press Enter once you've finished registering there (Ctrl+C to quit)... ")
        try:
            state = client.login()
        except NotRegisteredError:
            print(f"\nStill not registered. Finish registration at {e.registration_url} "
                  f"and re-run this script.", file=sys.stderr)
            return 2
    if state != "registered":
        print(f"userState came back '{state}', not 'registered' — can't continue.",
              file=sys.stderr)
        return 2
    print("Logged in.")

    if args.status:
        print(json.dumps(client.my_complaints()["result"], ensure_ascii=False, indent=2))
        return 0

    if not args.dir:
        print("Nothing to do: pass --dir <folder> or --status.", file=sys.stderr)
        return 2

    photos = sorted(p for p in Path(args.dir).expanduser().iterdir()
                    if p.suffix.lower() in IMAGE_EXTS)
    if not photos:
        print(f"No images found in {args.dir}", file=sys.stderr)
        return 1
    print(f"Found {len(photos)} photo(s).")

    chain = resolve_category_chain(client)

    filed = []
    for i, photo in enumerate(photos, 1):
        gps = exif_gps(photo)
        if gps:
            lat, lon = gps
            src = "EXIF"
        else:
            print(f"[{i}/{len(photos)}] {photo.name}: no GPS in EXIF.")
            raw = input("  enter 'lat,lon' (or blank to skip this photo): ").strip()
            if not raw:
                print("  skipped.")
                continue
            lat, lon = (float(x) for x in raw.split(","))
            src = "manual"

        image_url = f"{args.photo_base_url.rstrip('/')}/{photo.name}" if args.photo_base_url else None

        print(f"\n[{i}/{len(photos)}] {photo.name}")
        print(f"    location : {lat:.6f}, {lon:.6f} ({src})")
        print(f"    text     : {args.description}")
        print(f"    photo url: {image_url or '(none — submitting without a photo)'}")
        if not args.yes:
            if input("    submit this complaint? [y/N] ").strip().lower() != "y":
                print("    skipped.")
                continue

        resp = client.submit_complaint(
            description=args.description, latitude=lat, longitude=lon,
            location=f"{lat:.6f},{lon:.6f}", image_url=image_url,
            citizen_first_name=client.first_name, citizen_email=client.email,
            **chain,
        )
        token = resp.get("result", resp)
        print(f"    submitted -> {token}")
        filed.append((photo.name, token))

    print(f"\nDone. Filed {len(filed)} complaint(s):")
    for name, tok in filed:
        print(f"  {name} -> {tok}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
