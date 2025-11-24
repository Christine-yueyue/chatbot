import pytest

from backend import main


@pytest.mark.asyncio
async def test_scan_process_inserts_when_severe(monkeypatch):
    presc = {
        "id": 1,
        "patient_id": 42,
        "notes": "Patient reports severe chest pain after taking medication.",
        "issued_on": "2025-11-24T12:00:00.000Z",
    }

    async def fake_analyze_severity_for_prescription(text):
        return True

    def fake_fetch_table(name, params=None):
        return {"data": [presc]}

    inserted = []

    def fake_insert_record(table_name, payload):
        inserted.append((table_name, payload))
        return {"ok": True}

    monkeypatch.setattr(main, "fetch_table", fake_fetch_table)
    monkeypatch.setattr(main, "insert_record", fake_insert_record)
    monkeypatch.setattr(main, "analyze_severity_for_prescription", fake_analyze_severity_for_prescription)

    await main.scan_and_process_prescriptions()
import pytest

from backend import main


@pytest.mark.asyncio
async def test_scan_process_inserts_when_severe(monkeypatch):
    presc = {
        "id": 1,
        "patient_id": 42,
        "notes": "Patient reports severe chest pain after taking medication.",
        "issued_on": "2025-11-24T12:00:00.000Z",
    }

    async def fake_analyze_severity_for_prescription(text):
        return True

    def fake_fetch_table(name, params=None):
        return {"data": [presc]}

    inserted = []

    def fake_insert_record(table_name, payload):
        inserted.append((table_name, payload))
        return {"ok": True}

    monkeypatch.setattr(main, "fetch_table", fake_fetch_table)
    monkeypatch.setattr(main, "insert_record", fake_insert_record)
    monkeypatch.setattr(main, "analyze_severity_for_prescription", fake_analyze_severity_for_prescription)

    await main.scan_and_process_prescriptions()

    assert len(inserted) == 1
    assert inserted[0][0] == "patient_feedback"
    payload = inserted[0][1]
    assert payload["id"] == presc["id"]
    assert payload["patient_id"] == presc["patient_id"]
    inserted = []
