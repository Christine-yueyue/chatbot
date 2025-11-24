Frontend: React
Backend: FastAPI

# Frontend Guide(locally)
This project’s frontend runs on http://localhost:3000/ by default.

cd /Users/...Path.../feedback-management-main/frontend
npm install
npm start

The app will be available at: http://localhost:3000/

# Backend Guide(locally)
The backend is a Python service that can be run directly from the project’s backend directory.

Open a new terminal:
cd /Users/...Path.../feedback-management-main/backend
python3 main.py

# Instruction for the AI-Agent
Currently, our program implements the following main functions:

1. The frontend chatbot can send a feedback message. 

Input: Patient ID + feedback Example: "Hi, my Patient ID is 3. I received blood test before. After starting the new blood pressure medicine, I noticed occasional dizziness and mild headaches. My blood pressure readings are better, but I’m concerned about these side effects."

Output: "Immediate attention required. Your doctor will be notified." ---sever "There’s no urgent concern at this time. Please keep track of how you’re feeling." ---NOT sever

what can it do:
    Combine multiple tables' info into a prompt
    Generate feedback summary (LLM)
    Analyze feedback type (LLM)
    Analyze severity (LLM)
    Save result to database via API
    Return result to frontend (the Output)

2. The AI Agent can do analysis automatically.
To be specific, every 30 seconds, the system polls the prescription table to check for new entries. 
If new data is found, it is automatically analyzed. To control the number of database writes, only entries with high severity are written to the patient_feedback table. 
Non-severe cases are temporarily logged instead of being saved to the database.

Todo List
1. deploye the system on AWS 
2. implemente automatic patient ID retrieval from eHospital system
3. enable voice input

## Behavior
For feedback analysis from chatbot:
- Extracts feedback data from user input.
- Analyzes the severity of feedback.
- Uses AI to evaluate severity and returns "true" or "false".
- Classifies feedback type.
- Categorizes feedback as "treatment", "service", or "medication".
- Stores feedback in the database. Saves structured feedback data after classification and severity analysis.
- Notifies doctors if the feedback is severe.

For automated analysis agent:
- Polls `/table/prescription` and compares `issued_on` to `backend/.last_prescription_scan`.
- Only inserts into `patient_feedback` when `is_severe` is `true`.
- Persists last scan timestamp in `backend/.last_prescription_scan`.
- Non-severe analyses logged only.