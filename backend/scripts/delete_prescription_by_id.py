#!/usr/bin/env python3
"""Find and delete prescription records matching a given prescription_id.

By default the script runs in dry-run mode and prints matched records. Use
--force to actually attempt deletion via HTTP DELETE to the table API.

Usage (dry-run):
  python backend/scripts/delete_prescription_by_id.py --prescription_id 12

To actually delete (be careful):
  python backend/scripts/delete_prescription_by_id.py --prescription_id 12 --force
"""
import os
import requests
import argparse
import sys
import json

API_BASE = os.getenv("API_BASE_URL", "https://aetab8pjmb.us-east-1.awsapprunner.com/table/")


def fetch_table(table_name: str):
    url = API_BASE.rstrip("/") + f"/{table_name}"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()


def try_delete(table_name: str, record_id: int):
    # Primary attempt: HTTP DELETE to /table/{table_name}/{id}
    base = API_BASE.rstrip("/")
    url = f"{base}/{table_name}/{record_id}"
    try:
        r = requests.delete(url, timeout=15)
        if r.status_code in (200, 204):
            return True, f"Deleted via DELETE {url} (status {r.status_code})"
        else:
            return False, f"DELETE {url} returned {r.status_code}: {r.text}"
    except Exception as exc:
        return False, f"DELETE {url} exception: {exc}"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--prescription_id", type=int, required=True)
    p.add_argument("--force", action="store_true", help="Actually perform deletions (unsafe)")
    args = p.parse_args()

    table = "prescription"
    print(f"Using API_BASE={API_BASE}")
    data = fetch_table(table)
    records = data.get("data") if isinstance(data, dict) else []

    matches = []
    for rec in records:
        # match either explicit field or id equivalence
        if rec.get("prescription_id") == args.prescription_id or rec.get("id") == args.prescription_id:
            matches.append(rec)

    if not matches:
        print(f"No matching records found for prescription_id={args.prescription_id}")
        return

    print(f"Found {len(matches)} matching record(s):")
    for rec in matches:
        print(json.dumps(rec, indent=2, ensure_ascii=False))

    if not args.force:
        print("\nDry-run: no deletions performed. Re-run with --force to delete.")
        return

    print("\nPerforming deletions (force mode).")
    for rec in matches:
        # choose a numeric id for deletion; prefer 'id' then 'prescription_id'
        record_id = rec.get("id") or rec.get("prescription_id")
        if not record_id:
            print("Skipping record without id field:", rec)
            continue
        ok, msg = try_delete(table, record_id)
        print(msg)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("Error:", e, file=sys.stderr)
        sys.exit(1)
