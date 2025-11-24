#!/usr/bin/env python3
"""Find and delete patient_feedback records matching given patient_id values.

Dry-run by default; use --force to actually attempt deletion.

Usage (dry-run):
  python backend/scripts/delete_patient_feedback_by_patient.py --patient_id 55 --patient_id 101

To perform deletions:
  python backend/scripts/delete_patient_feedback_by_patient.py --patient_id 55 --patient_id 101 --force
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
    p.add_argument("--patient_id", type=int, action="append", required=True,
                   help="Patient id to remove (can specify multiple times)")
    p.add_argument("--force", action="store_true", help="Actually perform deletions (unsafe)")
    args = p.parse_args()

    table = "patient_feedback"
    print(f"Using API_BASE={API_BASE}")
    data = fetch_table(table)
    records = data.get("data") if isinstance(data, dict) else []

    to_remove = []
    for rec in records:
        if rec.get("patient_id") in args.patient_id:
            to_remove.append(rec)

    if not to_remove:
        print(f"No matching patient_feedback records found for patient_ids={args.patient_id}")
        return

    print(f"Found {len(to_remove)} matching record(s):")
    for rec in to_remove:
        print(json.dumps(rec, indent=2, ensure_ascii=False))

    if not args.force:
        print("\nDry-run: no deletions performed. Re-run with --force to delete.")
        return

    print("\nPerforming deletions (force mode).")
    for rec in to_remove:
        record_id = rec.get("id")
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
