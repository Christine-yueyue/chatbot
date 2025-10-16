# Patient Feedback Chatobot update 202510
- **Frontend**: React
- **Backend**: FastAPI

Input: Patient ID + feedback
Example: "Hi, my Patient ID is 3. I received blood test before. After starting the new blood pressure medicine, I noticed occasional dizziness and mild headaches. My blood pressure readings are better, but I’m concerned about these side effects."

Output: 
"Immediate attention required. Your doctor will be notified." ---sever
"There’s no urgent concern at this time. Please keep track of how you’re feeling."  ---NOT sever

what can it do:
1. Combine multiple tables' info into a prompt
2. Generate feedback summary (LLM)
3. Analyze feedback type (LLM)
4. Analyze severity (LLM)
5. Save result to database via API
6. Return result to frontend (the Output)



# Patient Feedback Chatobot

## Tech Stack
- **Frontend**: React
- **Backend**: FastAPI
- **Deployment**:
  - Backend: [Heroku](https://chatbot-2024-90539106da8b.herokuapp.com/)
  - Frontend: TBD


## Backend API

### POST `/chatbot/`

This is the main endpoint that receives user feedback and returns assistant responses.

**Example:**
```bash
curl -X POST http://localhost:8000/chatbot/ \
     -H "Content-Type: application/json" \
     -d '{"message": "1006. Treatment: Physical Therapy. Feedback: Excellent sessions but waiting times were too long."}'
```
Response:
```
{
  "response": "Thank you for your feedback! We have notified the doctor.",
  "assistant_response": "Immediate action recommended.",
  "suggested_treatment": "Consult a doctor as soon as possible."
}
```




## Introduction

### **Feature Functions**  
These functions implement the core business logic of the application:  

- **Extracts feedback data from user input**  
  - Identifies patient ID, treatment type, and feedback content.  
  - Ensures correct data formatting and returns structured JSON data.  

- **Analyzes the severity of feedback**  
  - Determines if patient feedback indicates an urgent issue.  
  - Checks historical data to detect worsening conditions.  
  - Uses AI to evaluate severity and returns `"true"` or `"false"`.  

- **Classifies feedback type**  
  - Categorizes feedback as `"treatment"`, `"service"`, or `"medication"`.  

- **Stores feedback in the database**  
  - Saves structured feedback data after classification and severity analysis.  
  - Notifies doctors if the feedback is severe.  

- **Generates treatment suggestions**  
  - Uses AI to propose potential treatment improvements based on feedback.  
  - Provides suggestions for doctors to review.  

### **Technical Functions**  
These functions handle system architecture, database operations, logging, and error handling:  

- **Ensures safe AI API calls**  
  - Wraps AI function calls with timeout handling and error logging.  
  - Prevents API failures from disrupting the main workflow.  

- **Logs AI operations**  
  - Records AI-related activities, including inputs and returned results.  

- **Handles FastAPI startup and shutdown processes**  
  - Creates and cleans up the database connection pool.  

- **Stores notifications in the doctor’s mailbox**  
  - Saves severe feedback and AI-generated treatment suggestions for doctors.  

- **Configures CORS middleware**  
  - Enables secure cross-origin requests from the frontend.  

- **Manages logging system**  
  - Implements a rotating file handler to store logs efficiently.  
  - Records errors, warnings, and debug information for troubleshooting.  

These functions collectively enable patient feedback extraction, analysis, storage, and notification while leveraging AI for automatic classification and medical decision support.



## Getting Started

Frontend:

```bash
npm start
```

Backend:

```bash
cd backend
uvicorn main:app --reload
```

