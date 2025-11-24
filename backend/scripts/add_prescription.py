#!/usr/bin/env python3
"""Simple script to POST a prescription record to the external API for testing.

Usage:
    python backend/scripts/add_prescription.py --patient_id 1 --text "Take 1 tablet nightly" --issued_on now

If --issued_on now, script will generate current UTC ISO timestamp with Z.
"""
import argparse
import json
import os
from datetime import datetime, timezone

import requests

API_BASE = os.getenv("API_BASE_URL", "https://aetab8pjmb.us-east-1.awsapprunner.com/table/")


def post_prescription(payload: dict):
    url = API_BASE.rstrip("/") + "/prescription"
    resp = requests.post(url, json=payload)
    resp.raise_for_status()
    return resp.json()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--prescription_id", type=int, default=None)
    p.add_argument("--patient_id", type=int, required=True)
    p.add_argument("--doctor_id", type=int, default=1)
    p.add_argument("--medicine_name", type=str, required=True)
    p.add_argument("--dosage", type=str, default="")
    p.add_argument("--start_date", type=str, default=None)
    p.add_argument("--end_date", type=str, default=None)
    p.add_argument("--notes", type=str, default="")
    p.add_argument("--issued_on", type=str, default="now",
                   help="ISO timestamp or 'now' to use current UTC time")
    p.add_argument("--status", type=str, default="active")
    args = p.parse_args()

    if args.issued_on == "now":
        issued_on = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    else:
        issued_on = args.issued_on

    payload = {
        # The API may map prescription_id to id server-side; include if provided
        **({"prescription_id": args.prescription_id} if args.prescription_id is not None else {}),
        "patient_id": args.patient_id,
        "doctor_id": args.doctor_id,
        "medicine_name": args.medicine_name,
        "dosage": args.dosage,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "notes": args.notes,
        "issued_on": issued_on,
        "status": args.status,
    }

    print("Posting prescription:", json.dumps(payload, indent=2))
    res = post_prescription(payload)
    print("Response:", res)
