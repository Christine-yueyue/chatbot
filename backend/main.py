from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import requests
import json
import logging
from datetime import datetime
from openai import AsyncOpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = FastAPI()

# === Config ===
API_BASE_URL = "https://aetab8pjmb.us-east-1.awsapprunner.com/table/"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "*")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === Logging ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === OpenAI client ===
client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# === Data model ===
class ChatQuery(BaseModel):
    patient_id: int
    feedback: str


# Interact with database by using API 
def get_from_api(table_name: str, params: dict = None):
    url = f"{API_BASE_URL}{table_name}"
    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"GET {url} failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch {table_name}")

def post_to_api(table_name: str, payload: dict):
    url = f"{API_BASE_URL}{table_name}"
    try:
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"POST {url} failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to post to {table_name}")


# === Build combined patient prompt ===
async def build_patient_prompt(patient_id: int, new_feedback: str) -> str:
    """Combine patient_feedback + medical_history into one detailed prompt"""
    try:
        feedback_data = get_from_api("patient_feedback", {"patient_id": patient_id})
        history_data = get_from_api("medical_history", {"patient_id": patient_id})

        # Format feedback records
        feedback_text = "\n".join(
            [f"{item['datetime']}: {item['feedback']}" for item in feedback_data.get("data", [])]
        ) or "No feedback records found."

        # Format medical history
        medical_text = "\n".join(
            [
                f"{item['last_updated']}: {item['treatment_given']} — Notes: {item['notes']}"
                for item in history_data.get("data", [])
            ]
        ) or "No medical history found."

        prompt = f"""
You are a medical severity analysis assistant.

Patient's historical feedback:
{feedback_text}

Patient's medical history:
{medical_text}

New feedback:
{new_feedback}

Based on the patient's historical feedback and medical history, decide whether the new feedback indicates a severe medical situation.
Respond ONLY with JSON:
{{"is_severe": "true"}} or {{"is_severe": "false"}}
"""
        return prompt.strip()

    except Exception as e:
        logger.error(f"Error building patient prompt: {e}")
        return new_feedback  # fallback


# === LLM severity analysis ===
async def analyze_is_severe(prompt: str) -> str:
    """Call LLM to determine severity"""
    try:
        result = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a clinical triage assistant."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )
        output = json.loads(result.choices[0].message.content)
        return "true" if output.get("is_severe", "false").lower() == "true" else "false"
    except Exception as e:
        logger.error(f"LLM analysis failed: {e}")
        return "false"

# === LLM feedback summarize ===
async def summarize_feedback(feedback: str) -> str:
    try:
        # Pre-clean obvious ID patterns before sending to LLM
        import re
        cleaned_feedback = re.sub(
            r"\b(?:my\s*)?(?:patient\s*id|id)\s*(?:is|:)?\s*\d+\b",
            "",
            feedback,
            flags=re.IGNORECASE,
        ).strip()

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": f"Summarize the following feedback in one sentence: {feedback}"
            }],
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Error summarizing feedback: {e}")
        return feedback
    
# === LLM feedback classification ===
async def classify_feedback_type(feedback: str) -> str:
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": f"""
Classify this feedback into one of the following categories:
1. symptom
2. treatment
3. follow-up
Only output the category name.
Feedback: {feedback}
"""
            }],
        )
        category = response.choices[0].message.content.strip().lower()
        if category not in ["symptom", "treatment", "follow-up"]:
            category = "general"
        return category
    except Exception as e:
        logger.error(f"Error classifying feedback type: {e}")
        return "general"


# === Main API endpoint ===
@app.post("/chatbot/")
async def chatbot_feedback(query: ChatQuery):
    """
    1. Combine multiple tables' info into a prompt
    2. Generate feedback summary
    3. Analyze feedback type
    4. Analyze severity
    5. Save result to database via API
    6. Return result to frontend
    """
    try:
        logger.info(f"Received feedback from patient {query.patient_id}")

        # Step 1: Build combined prompt
        prompt = await build_patient_prompt(query.patient_id, query.feedback)

        # Step 2: Generate summary
        summary = await summarize_feedback(query.feedback)

        # Step 3: Classify feedback type
        feedback_type = await classify_feedback_type(query.feedback)

        # Step 4: Analyze severity
        is_severe = await analyze_is_severe(prompt)
        logger.info(f"is_severe={is_severe}, type={feedback_type}")
        
       # Step 5: Save to API
        record = {
            "patient_id": query.patient_id,
            "feedback": summary,
            "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "is_severe": is_severe,
            "feedback_type": feedback_type,
        }
        post_to_api("patient_feedback", record)
        logger.info("Record saved to patient_feedback via API.")

        # Step 6: Respond to frontend
        return {
            "success": True,
            "is_severe": is_severe,
            "feedback_type": feedback_type,
            "summary": summary,
            "assistant_response": (
                "Immediate attention required. Your doctor will be notified."
                if is_severe == "true"
                else "There’s no urgent concern at this time. Please keep track of how you’re feeling."
            ),
        }

    except Exception as e:
        logger.error(f"Error processing chatbot feedback: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
