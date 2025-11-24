#!/usr/bin/env python3
"""Run a mocked one-off scan locally.

This script monkeypatches `backend.main` helpers so the scan reads a single
mocked prescription, forces the prescription-analyzer to return severe=True,
and replaces `insert_record` with a local printer so you can see what would be
inserted into `/table/patient_feedback`.

Usage (from repo root):
  python backend/scripts/run_mock_scan.py

No network calls are required by this script.
"""
import asyncio
from datetime import datetime, timezone
import json
import os

try:
    # import the backend package
    from backend import main
except Exception as exc:  # pragma: no cover - helpful error for new users
    raise SystemExit("Failed to import backend.main. Run this from the repo root so Python can import the 'backend' package.\nError: %s" % exc)


def make_mock_prescription():
    now_z = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "id": 999999,
        "patient_id": 42,
        "text": "Patient reports severe allergic reaction after taking MedX: hives, swelling, difficulty breathing.",
        "issued_on": now_z,
    }


def apply_mocks():
    # Mock fetch_table to return our single prescription
    def mock_fetch_table(table_name: str, params=None):
        if table_name == "prescription":
            return {"data": [make_mock_prescription()]}
        # keep default behavior for other tables
        return {"data": []}

    # Mock insert_record to print the payload instead of making a network call
    def mock_insert_record(table_name: str, payload: dict):
        print("--- mock insert_record called ---")
        print("table:", table_name)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        # return a fake API response structure
        return {"success": True, "inserted": payload}

    # Force the prescription analyzer to always return True (severe)
    async def mock_analyze_severity_for_prescription(text: str) -> bool:
        print("mock_analyze_severity_for_prescription: forcing severe=True for text:\n", text[:200])
        return True

    # Apply mocks onto backend.main
    main.fetch_table = mock_fetch_table
    main.insert_record = mock_insert_record
    main.analyze_severity_for_prescription = mock_analyze_severity_for_prescription


async def run_once():
    # Ensure persisted last scan is something older so the record is considered new
    main.last_prescription_scan = "1970-01-01T00:00:00Z"
    # apply mocks
    apply_mocks()

    print("Running mocked scan...\n")
    await main.scan_and_process_prescriptions()
    print("Mocked scan complete.\n")
    # Show the last_prescription_scan value after processing
    print("last_prescription_scan =>", main.last_prescription_scan)


if __name__ == "__main__":
    asyncio.run(run_once())
