from datetime import datetime
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import requests
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Optional OpenAI async client import. Keep import local to avoid hard failure if not configured.
try:
    from openai import AsyncOpenAI
except Exception:  # pragma: no cover - optional in some environments
    AsyncOpenAI = None

load_dotenv()

API_BASE_URL = os.getenv("API_BASE_URL", "https://aetab8pjmb.us-east-1.awsapprunner.com/table/")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "*")
NOTIFY_URL = os.getenv("NOTIFY_URL")  # optional external notification endpoint

SYSTEM_PROMPT_SUMMARIZE = """
You are a biomedical summarization assistant used in a clinical setting by doctors and patients.
Your task is to summarize patient feedback **strictly and only based on the original text**.

RULES:
- Do NOT add any information not present in the original text.
- Do NOT infer diagnosis, medical causes, severity, or prognosis.
- Do NOT reinterpret symptoms beyond what the patient explicitly said.
- Keep wording factual, neutral, and free of assumptions.
- Only condense, paraphrase, or organize the provided content.
- If the input is vague, the summary must remain equally vague.

The summary must represent the patient's message accurately and without speculation.
"""

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Input model for chatbot endpoint
class ChatQuery(BaseModel):
    patient_id: int
    feedback: str

openai_client: Optional[Any] = None
scheduler = AsyncIOScheduler()

# restore last-scan timestamp in memory
LAST_SCAN_FILE = os.path.join(os.path.dirname(__file__), ".last_prescription_scan")
last_prescription_scan: str = "2024-01-01T00:00:00Z"

def _read_last_scan_file() -> str:
    """Read the last scan timestamp from disk. Return ISO string or default epoch with Z."""
    try:
        if os.path.exists(LAST_SCAN_FILE):
            with open(LAST_SCAN_FILE, "r", encoding="utf-8") as f:
                v = f.read().strip()
                if v:
                    return v
    except Exception as exc:
        logger.debug("_read_last_scan_file failed: %s", exc)
    return "2024-01-01T00:00:00Z"

def _write_last_scan_file(ts: str) -> None:
    """Persist the last scan timestamp to disk (atomic write)."""
    try:
        tmp = LAST_SCAN_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(ts)
        os.replace(tmp, LAST_SCAN_FILE)
    except Exception as exc:
        logger.error("_write_last_scan_file failed: %s", exc)


def _parse_iso_ts(ts: str) -> Optional[datetime]:
    """Parse ISO 8601 timestamps including trailing 'Z' into aware datetime in UTC.

    Returns None if parsing fails.
    """
    if not ts:
        return None
    try:
        # Replace Z with +00:00 so fromisoformat can parse it
        if ts.endswith("Z"):
            ts2 = ts.replace("Z", "+00:00")
        else:
            ts2 = ts
        return datetime.fromisoformat(ts2)
    except Exception:
        try:
            # fallback: try parsing without fractional seconds
            return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z")
        except Exception:
            logger.debug("_parse_iso_ts failed for %s", ts)
            return None


# === HTTP helpers ===
def fetch_table(table_name: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Fetch rows from the external table API and return parsed JSON.

    Raises HTTPException on failure so callers can return 5xx.
    """
    url = f"{API_BASE_URL.rstrip('/')}/{table_name}"
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.error("fetch_table failed for %s: %s", table_name, exc)
        raise HTTPException(status_code=502, detail=f"Failed to fetch {table_name}")

def insert_record(table_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Insert a record into the external table API.

    Raises HTTPException on failure.
    """
    url = f"{API_BASE_URL.rstrip('/')}/{table_name}"
    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.error("insert_record failed for %s: %s", table_name, exc)
        raise HTTPException(status_code=502, detail=f"Failed to post to {table_name}")

# === Text composition & LLM wrappers ===
def compose_patient_context(patient_id: int, new_feedback: str) -> str:
    """Compose a compact context combining historical feedback and medical history.

    If the external tables are unavailable, fall back to the new feedback only.
    """
    try:
        feedback_data = fetch_table("patient_feedback", {"patient_id": patient_id})
        history_data = fetch_table("medical_history", {"patient_id": patient_id})

        feedback_items = feedback_data.get("data", []) if isinstance(feedback_data, dict) else []
        history_items = history_data.get("data", []) if isinstance(history_data, dict) else []

        feedback_text = "\n".join(f"{it.get('datetime')}: {it.get('feedback')}" for it in feedback_items) or "No feedback records."
        medical_text = "\n".join(
            f"{it.get('last_updated')}: {it.get('treatment_given')} — Notes: {it.get('notes')}" for it in history_items
        ) or "No medical history."

        return (
            f"Patient ID: {patient_id}\n\n"
            f"Historical feedback:\n{feedback_text}\n\n"
            f"Medical history:\n{medical_text}\n\n"
            f"New feedback:\n{new_feedback}"
        )
    except HTTPException:
        logger.info("compose_patient_context: external tables unavailable, using new feedback only")
        return f"New feedback:\n{new_feedback}"
    except Exception as exc:
        logger.error("compose_patient_context error: %s", exc)
        return f"New feedback:\n{new_feedback}"


async def analyze_severity(context: str) -> bool:
    """Return True if the model determines the situation is severe.

    This implementation is defensive: if the model call fails or is not configured, returns False.
    """
    global openai_client
    if not openai_client:
        logger.info("analyze_severity: OpenAI client not configured; defaulting to non-severe")
        return False

    try:
        # Ask the model to return a short JSON string containing {"is_severe": "true"|"false"}
        prompt = (
            "You are a clinical triage assistant. Given the following context, "
            "respond with a single JSON object containing only the field 'is_severe' with value 'true' or 'false'.\n\n"
            f"Context:\n{context}"
        )
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": prompt},
            ],
        )
        raw = getattr(response.choices[0].message, "content", "{}").strip()
        logger.debug("analyze_severity raw LLM response: %s", raw)
        # Try to find JSON in the response
        try:
            data = json.loads(raw)
        except Exception:
            # attempt to extract JSON substring
            import re as _re
            m = _re.search(r"\{.*\}", raw, _re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group(0))
                except Exception:
                    data = {}
            else:
                data = {}
        logger.debug("analyze_severity parsed JSON: %s", data)

        return str(data.get("is_severe", "false")).lower() == "true"
    except Exception as exc:
        logger.error("analyze_severity failed: %s", exc)
        return False


async def analyze_severity_for_prescription(prescription_text: str) -> bool:
    """Prescription-specific severity analysis. Keeps prompt focused on prescription risk.

    Returns True when the model indicates a serious adverse event or urgent concern.
    """
    global openai_client
    if not openai_client:
        logger.info("analyze_severity_for_prescription: OpenAI client not configured; defaulting to non-severe")
        return False

    try:
        prompt = (
            "You are a clinical triage assistant assessing prescription-related risk. "
            "Given the prescription text, respond with a single JSON object {\"is_severe\": \"true\"|\"false\"} where 'true' indicates an urgent safety concern (e.g., dangerous doses, contraindications, acute adverse symptoms).\n\n"
            f"Prescription:\n{prescription_text}"
        )
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
        )
        raw = getattr(response.choices[0].message, "content", "{}").strip()
        logger.debug("analyze_severity_for_prescription raw LLM response: %s", raw)
        try:
            data = json.loads(raw)
        except Exception:
            import re as _re
            m = _re.search(r"\{.*\}", raw, _re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group(0))
                except Exception:
                    data = {}
            else:
                data = {}
        logger.debug("analyze_severity_for_prescription parsed JSON: %s", data)

        return str(data.get("is_severe", "false")).lower() == "true"
    except Exception as exc:
        logger.error("analyze_severity_for_prescription failed: %s", exc)
        return False


async def summarize_feedback(feedback: str) -> str:
    """Ask the LLM to summarize the feedback in one sentence. If LLM missing, return a cleaned snippet."""
    global openai_client
    cleaned = re.sub(r"\b(?:my\s*)?(?:patient\s*id|id)\s*(?:is|:)?\s*\d+\b", "", feedback, flags=re.IGNORECASE).strip()
    if not openai_client:
        return (cleaned[:200] + "...") if len(cleaned) > 200 else cleaned

    try:
        resp = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_SUMMARIZE},
                {"role": "user", "content": f"Summarize the following feedback in one sentence: {feedback}"}
                ]
        )
        return resp.choices[0].message.content.strip()
    except Exception as exc:
        logger.error("summarize_feedback failed: %s", exc)
        return cleaned


async def classify_feedback_type(feedback: str) -> str:
    """Classify feedback into symptom/treatment/follow-up/general."""
    global openai_client
    if not openai_client:
        return "general"

    try:
        resp = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": (
                "Classify this feedback into one of: symptom, treatment, follow-up. "
                f"Only return the category name. Feedback: {feedback}"
            )}],
        )
        category = resp.choices[0].message.content.strip().lower()
        return category if category in {"symptom", "treatment", "follow-up"} else "general"
    except Exception as exc:
        logger.error("classify_feedback_type failed: %s", exc)
        return "general"


# === Notification actuator ===
def notify_severe_case(patient_id: int, summary: str) -> None:
    """Trigger an external notification. If NOTIFY_URL is set, POST to it; otherwise log at critical level."""
    payload = {"patient_id": patient_id, "summary": summary, "timestamp": datetime.utcnow().isoformat()}
    if NOTIFY_URL:
        try:
            resp = requests.post(NOTIFY_URL, json=payload, timeout=10)
            resp.raise_for_status()
            logger.info("notify_severe_case: notification sent for patient %s", patient_id)
            return
        except Exception as exc:
            logger.error("notify_severe_case POST failed: %s", exc)

    logger.critical("SEVERE: patient=%s summary=%s", patient_id, summary)


# === Core workflow ===
async def analyze_and_store_feedback(patient_id: int, raw_feedback: str) -> Tuple[bool, str, str]:
    """Analyze a piece of feedback, persist a normalized record, and return (is_severe, type, summary)."""
    context = compose_patient_context(patient_id, raw_feedback)
    summary = await summarize_feedback(raw_feedback)
    feedback_type = await classify_feedback_type(raw_feedback)
    is_severe = await analyze_severity(context)

    record = {
        "patient_id": patient_id,
        "feedback": summary,
        "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "is_severe": "true" if is_severe else "false",
        "feedback_type": feedback_type,
    }
    # For chatbot feedback: always persist to patient_feedback. Notify only for severe cases.
    try:
        insert_record("patient_feedback", record)
        if is_severe:
            notify_severe_case(patient_id, summary)
        else:
            logger.info("analyze_and_store_feedback: non-severe result for patient %s; inserted without notification", patient_id)
    except Exception as exc:
        logger.error("analyze_and_store_feedback: failed to insert patient_feedback: %s", exc)

    return is_severe, feedback_type, summary


# === Worker (proactive polling) ===
async def worker_task():
    """Periodic background task that processes new feedback items."""
    try:
        # worker dispatches to prescription-specific analyzer to keep chatbot flow unchanged
        await worker_task_analyze_prescription()
    except Exception as exc:
        logger.exception("worker_task failed: %s", exc)


async def worker_task_analyze_prescription():
    """A dedicated worker that scans prescriptions and analyzes them using a prescription-specific prompt.

    This keeps the chatbot feedback analysis flow unchanged.
    """
    try:
        logger.debug("worker_task_analyze_prescription: running scan")
        await scan_and_process_prescriptions()
    except Exception as exc:
        logger.exception("worker_task_analyze_prescription failed: %s", exc)


async def scan_and_process_prescriptions() -> None:
    """Poll /table/prescription and process newly issued/updated prescriptions.

    For each prescription whose `issued_on` is greater than the global
    `last_prescription_scan`, analyze severity, summarize the prescription text,
    and insert a new record into `/table/patient_feedback` following the
    project's required JSON schema. The prescription's original `id` is kept.
    After processing each record, update `last_prescription_scan` to that
    record's `issued_on` value.
    """
    global last_prescription_scan
    try:
        # ensure last_prescription_scan is a proper ISO string
        logger.info("scan_and_process_prescriptions: checking prescriptions since %s", last_prescription_scan)
        resp = fetch_table("prescription")
        records = resp.get("data", []) if isinstance(resp, dict) else []

        # parse current last scan to datetime
        last_dt = _parse_iso_ts(last_prescription_scan) or datetime.fromisoformat("1970-01-01T00:00:00+00:00")

        # Sort by parsed issued_on datetime
        def _issued_on_dt(r: Dict[str, Any]) -> datetime:
            d = _parse_iso_ts(r.get("issued_on") or "")
            return d or datetime.fromisoformat("1970-01-01T00:00:00+00:00")

        for rec in sorted(records, key=_issued_on_dt):
            issued_on = rec.get("issued_on")
            if not issued_on:
                continue

            issued_dt = _parse_iso_ts(issued_on)
            if not issued_dt:
                continue

            # skip records not newer than last scan
            if issued_dt <= last_dt:
                continue

            prescription_text = (rec.get("text") or rec.get("prescription") or rec.get("notes") or "").strip()
            if not prescription_text:
                logger.warning("scan_and_process_prescriptions: prescription id=%s has empty text/notes", rec.get("id"))
            patient_id = rec.get("patient_id")

            # Use prescription-specific analyzer for prescriptions
            is_severe_flag = await analyze_severity_for_prescription(prescription_text)
            summary = await summarize_feedback(prescription_text)

            # If LLM returns a generic prompt asking for input (common when empty input was sent),
            # fallback to a simple excerpt from the prescription text.
            if isinstance(summary, str):
                s_low = summary.lower().strip()
                if (not prescription_text) or s_low.startswith("please provide") or "please provide" in s_low or "no text" in s_low:
                    fallback = (prescription_text[:200] + "...") if len(prescription_text) > 200 else prescription_text
                    if fallback:
                        logger.info("scan_and_process_prescriptions: LLM summary looked like a prompt; using fallback summary for id=%s", rec.get("id"))
                        summary = fallback

            pf_record = {
                "id": rec.get("id"),
                "patient_id": patient_id,
                "feedback": summary,
                "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "is_severe": "true" if is_severe_flag else "false",
                "feedback_type": "prescription_update",
                "treatment": "Auto-scan and analyze prescription",
            }

            if is_severe_flag:
                insert_record("patient_feedback", pf_record)
                logger.info("scan_and_process_prescriptions: inserted patient_feedback for prescription id=%s", rec.get("id"))
            else:
                logger.info("scan_and_process_prescriptions: prescription id=%s not severe; logged only", rec.get("id"))

            # Update last scan timestamp after processing this record (store in Z form)
            # Normalize to UTC Z format
            new_ts = issued_dt.isoformat()
            if new_ts.endswith("+00:00"):
                new_ts = new_ts.replace("+00:00", "Z")
            last_prescription_scan = new_ts
            _write_last_scan_file(last_prescription_scan)

    except HTTPException:
        logger.info("scan_and_process_prescriptions: prescription table unavailable")
    except Exception as exc:
        logger.exception("scan_and_process_prescriptions failed: %s", exc)


# === FastAPI endpoints & lifecycle ===
@app.post("/chatbot/")
async def chatbot_feedback(query: ChatQuery):
    """Reactive endpoint used by the frontend. Runs the same analysis workflow synchronously for the request."""
    try:
        logger.info("API: received feedback for patient %s", query.patient_id)
        is_severe, feedback_type, summary = await analyze_and_store_feedback(query.patient_id, query.feedback)

        return {
            "success": True,
            "is_severe": "true" if is_severe else "false",
            "feedback_type": feedback_type,
            "summary": summary,
            "assistant_response": (
                "Immediate attention required. Your doctor will be notified." if is_severe else "There’s no urgent concern at this time. Please keep track of how you’re feeling."
            ),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("chatbot_feedback failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.on_event("startup")
async def startup_event():
    """Initialize optional OpenAI client and start the periodic worker."""
    global openai_client, scheduler
    # load persisted last scan timestamp
    try:
        global last_prescription_scan
        last_prescription_scan = _read_last_scan_file()
        logger.info("Loaded last_prescription_scan=%s", last_prescription_scan)
    except Exception:
        logger.debug("Failed to load persisted last_prescription_scan; using default")
    if AsyncOpenAI and OPENAI_API_KEY:
        try:
            openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
            logger.info("OpenAI client configured")
        except Exception as exc:
            openai_client = None
            logger.error("Failed to initialize OpenAI client: %s", exc)
    else:
        logger.info("OpenAI client not configured (missing package or API key)")

    # schedule the worker every 30 seconds
    scheduler.add_job(worker_task, "interval", seconds=30)
    scheduler.start()
    logger.info("Background worker scheduled to run every 30s")


@app.on_event("shutdown")
def shutdown_event():
    try:
        scheduler.shutdown(wait=False)
    except Exception:
        logger.debug("scheduler shutdown encountered an issue")
    logger.info("Application shutdown complete")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)