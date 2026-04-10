import os
import datetime
import logging
import requests
import nest_asyncio
from google.cloud import datastore
from dotenv import load_dotenv

nest_asyncio.apply()
load_dotenv()

PROJECT_ID = "study-buddy-bro-guide"
LOCATION   = "us-central1"
MODEL      = "gemini-2.5-flash"   # ✅ Updated - confirmed available in your Vertex AI Studio

db = datastore.Client(
    project=PROJECT_ID,
    database="study-buddy-datastore"
)

# ─────────────────────────────────────────
# VERTEX AI AUTH HELPER
# ─────────────────────────────────────────
def get_vertex_token() -> str:
    """Get a fresh access token using Application Default Credentials."""
    import google.auth
    import google.auth.transport.requests
    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    auth_req = google.auth.transport.requests.Request()
    creds.refresh(auth_req)
    return creds.token

def build_vertex_url(model: str = MODEL) -> str:
    return (
        f"https://{LOCATION}-aiplatform.googleapis.com/v1"
        f"/projects/{PROJECT_ID}"
        f"/locations/{LOCATION}"
        f"/publishers/google/models/{model}:generateContent"
    )

# ─────────────────────────────────────────
# FIRESTORE MEMORY
# ─────────────────────────────────────────
def save_conversation(session_id: str, role: str, message: str):
    try:
        truncated = message[:1400] if len(message) > 1400 else message
        key = db.key("conversations", f"{session_id}_{datetime.datetime.utcnow().timestamp()}")
        entity = datastore.Entity(key=key, exclude_from_indexes=("message",))
        entity.update({
            "session_id": session_id,
            "role": role,
            "message": truncated,
            "timestamp": datetime.datetime.utcnow()
        })
        db.put(entity)
    except Exception as e:
        logging.error(f"Save conversation error: {e}")

def get_conversation_history(session_id: str) -> list:
    try:
        query = db.query(kind="conversations")
        query.add_filter(
            filter=datastore.query.PropertyFilter("session_id", "=", session_id)
        )
        query.order = ["timestamp"]
        messages = list(query.fetch(limit=10))
        return [{"role": m["role"], "message": m["message"]} for m in messages]
    except Exception as e:
        logging.error(f"Get history error: {e}")
        return []

def save_student_profile(session_id: str, data: dict):
    try:
        key = db.key("students", session_id)
        entity = db.get(key) or datastore.Entity(key=key)
        entity.update(data)
        db.put(entity)
    except Exception as e:
        logging.error(f"Save profile error: {e}")

def get_student_profile(session_id: str) -> dict:
    try:
        key = db.key("students", session_id)
        entity = db.get(key)
        return dict(entity) if entity else {}
    except Exception:
        return {}

# ─────────────────────────────────────────
# CORE VERTEX AI CALL
# ─────────────────────────────────────────
def call_gemini_with_system(system_prompt: str, user_message: str, model: str = None) -> str:
    import time

    FALLBACK_MODELS = [
        "gemini-2.5-flash",        # ✅ Primary - confirmed in your Vertex AI Studio
        "gemini-2.5-flash-lite",   # ✅ Fallback 1
        "gemini-2.0-flash",        # ✅ Fallback 2
        "gemini-2.0-flash-lite",   # ✅ Fallback 3
    ]

    models_to_try = FALLBACK_MODELS if model is None else [model] + [m for m in FALLBACK_MODELS if m != model]

    for current_model in models_to_try:
        for attempt in range(2):
            try:
                token   = get_vertex_token()
                url     = build_vertex_url(current_model)
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type":  "application/json"
                }
                payload = {
                    "system_instruction": {
                        "parts": [{"text": system_prompt}]
                    },
                    "contents": [
                        {"role": "user", "parts": [{"text": user_message}]}
                    ],
                    "generationConfig": {
                        "temperature": 0.7,
                        "maxOutputTokens": 1024
                    }
                }

                r = requests.post(url, headers=headers, json=payload, timeout=60)

                if r.status_code == 429:
                    logging.warning(f"Rate limited on {current_model}, waiting...")
                    time.sleep(10)
                    continue

                if r.status_code == 404:
                    logging.warning(f"Model {current_model} not found (404), trying next...")
                    break  # break inner loop, try next model

                r.raise_for_status()
                return r.json()["candidates"][0]["content"]["parts"][0]["text"]

            except requests.exceptions.HTTPError as e:
                logging.error(f"HTTP error [{current_model}] attempt {attempt + 1}: {e}")
                if attempt == 1:
                    break  # try next model
                time.sleep(3)

            except Exception as e:
                logging.error(f"Unexpected error [{current_model}] attempt {attempt + 1}: {e}")
                if attempt == 1:
                    break  # try next model
                time.sleep(3)

    return "No available model found. Please check Vertex AI Model Garden for your project."

# ─────────────────────────────────────────
# SUB-AGENTS
# ─────────────────────────────────────────
def schedule_agent(message: str, session_id: str) -> str:
    system = """You are a study schedule manager for Study Buddy Bro.
    Help students plan their study sessions and track exam dates.
    Be encouraging, realistic and specific about dates and times.
    When the student mentions an exam, suggest a study plan with specific days."""
    return call_gemini_with_system(system, message)

def quiz_agent(message: str) -> str:
    system = """You are a quiz generator for Study Buddy Bro.
    Generate MCQ questions with 4 options (A, B, C, D) and correct answers.
    Always include explanations. Make questions educational and clear."""
    return call_gemini_with_system(system, message)

def explainer_agent(message: str) -> str:
    system = """You are a patient tutor for Study Buddy Bro.
    Break down complex topics into:
    1. Simple definition
    2. Real-world analogy
    3. Key points (bullet list)
    4. One worked example
    Always end with: Want me to quiz you on this? 📝"""
    return call_gemini_with_system(system, message)

def progress_agent(message: str, session_id: str) -> str:
    from tools import get_progress
    progress_data = get_progress(session_id)
    system = """You are a study progress tracker for Study Buddy Bro.
    Show the student their progress, motivate them and suggest what to study next."""
    return call_gemini_with_system(system, f"{message}\n\nCurrent progress data:\n{progress_data}")

def reminder_agent(message: str) -> str:
    system = """You are a study reminder assistant for Study Buddy Bro.
    Help students set reminders and send motivating study alerts.
    Keep messages short, clear and encouraging."""
    return call_gemini_with_system(system, message)

# ─────────────────────────────────────────
# PRIMARY AGENT — routes to sub-agents
# ─────────────────────────────────────────
def run_primary_agent(session_id: str, user_message: str, history: list) -> str:
    context = ""
    if history:
        context = "Previous conversation:\n"
        for h in history[-5:]:
            context += f"{h['role'].upper()}: {h['message']}\n"
        context += "\n"

    routing_prompt = f"""You are Study Buddy Bro — a friendly AI study assistant.

You have 5 specialized agents:
- schedule_agent: study plans, exams, calendar, timetables, scheduling
- quiz_agent: MCQs, flashcards, practice questions, testing knowledge
- explainer_agent: explaining topics, concepts, definitions, understanding
- progress_agent: tracking completed topics, study streaks, progress
- reminder_agent: email reminders, notifications, alerts

{context}Student says: "{user_message}"

First, identify which agents are needed (can be multiple).
Then respond as Study Buddy Bro — warm, helpful and encouraging.

If they need scheduling: create a specific study plan with days and hours.
If they need explanation: explain clearly with examples.
If they need a quiz: generate 3-5 MCQ questions immediately.
If they need progress: show their study statistics.
If they need reminders: confirm the reminder setup.

Always end with an encouraging next step.
Be conversational, friendly and student-focused. 📚"""

    msg_lower  = user_message.lower()
    responses  = []

    if any(w in msg_lower for w in ["quiz", "test me", "question", "mcq", "flashcard", "practice"]):
        responses.append(quiz_agent(user_message))

    elif any(w in msg_lower for w in ["explain", "what is", "what are", "how does", "tell me about", "understand", "definition"]):
        responses.append(explainer_agent(user_message))

    elif any(w in msg_lower for w in ["exam", "schedule", "plan", "timetable", "days", "prepare", "calendar", "session"]):
        responses.append(schedule_agent(user_message, session_id))

    elif any(w in msg_lower for w in ["progress", "studied", "completed", "streak", "how much", "topics done"]):
        responses.append(progress_agent(user_message, session_id))

    elif any(w in msg_lower for w in ["remind", "reminder", "notify", "alert", "email"]):
        responses.append(reminder_agent(user_message))

    else:
        responses.append(call_gemini_with_system(routing_prompt, user_message))

    return "\n\n".join(responses)

# ─────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────
def run_agent_with_memory(session_id: str, user_message: str) -> str:
    save_conversation(session_id, "user", user_message)
    history = get_conversation_history(session_id)

    try:
        reply = run_primary_agent(session_id, user_message, history)
    except Exception as e:
        reply = f"Sorry, something went wrong: {str(e)} — Please try again! 😅"

    save_conversation(session_id, "assistant", reply)
    save_student_profile(session_id, {
        "last_active": datetime.datetime.utcnow(),
        "session_id":  session_id
    })

    return reply

def get_agent():
    return None