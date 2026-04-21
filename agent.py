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
MODEL      = "gemini-2.5-flash"

db = datastore.Client(
    project=PROJECT_ID,
    database="study-buddy-datastore"
)

# ─────────────────────────────────────────
# VERTEX AI AUTH HELPER
# ─────────────────────────────────────────
def get_vertex_token() -> str:
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
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
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
                        "maxOutputTokens": 2048
                    }
                }

                r = requests.post(url, headers=headers, json=payload, timeout=60)

                if r.status_code == 429:
                    logging.warning(f"Rate limited on {current_model}, waiting...")
                    time.sleep(10)
                    continue

                if r.status_code == 404:
                    logging.warning(f"Model {current_model} not found (404), trying next...")
                    break

                r.raise_for_status()
                return r.json()["candidates"][0]["content"]["parts"][0]["text"]

            except requests.exceptions.HTTPError as e:
                logging.error(f"HTTP error [{current_model}] attempt {attempt + 1}: {e}")
                if attempt == 1:
                    break
                time.sleep(3)

            except Exception as e:
                logging.error(f"Unexpected error [{current_model}] attempt {attempt + 1}: {e}")
                if attempt == 1:
                    break
                time.sleep(3)

    return "No available model found. Please check Vertex AI Model Garden for your project."

# ─────────────────────────────────────────
# SUB-AGENTS
# ─────────────────────────────────────────

def schedule_agent(message: str, session_id: str) -> str:
    system = """You are a study schedule manager for Study Buddy Bro.
Help students plan their study sessions and track exam dates.
Be encouraging, realistic and specific about dates and times.
When the student mentions an exam, suggest a study plan with specific days and hours.
Format study plans as a clean table or bullet list with days, times, and topics.
Always ask how many hours per day they can study if not mentioned."""
    return call_gemini_with_system(system, message)


def quiz_agent(message: str) -> str:
    """
    Returns a special marker so main.py knows to call the JSON quiz endpoint.
    The actual quiz JSON is generated by tools.generate_quiz_json().
    """
    # Extract topic from message
    msg_lower = message.lower()
    # Try to find topic after "quiz me on", "quiz on", "test me on", etc.
    topic = message
    for phrase in ["quiz me on", "quiz on", "test me on", "test on", "questions on", "questions about", "mcq on", "mcq about"]:
        if phrase in msg_lower:
            topic = message[msg_lower.index(phrase) + len(phrase):].strip()
            break
    # Clean up topic
    topic = topic.strip("?.,! ") or "General Knowledge"
    return f"QUIZ_JSON:{topic}"


def explainer_agent(message: str) -> str:
    """
    Detects difficulty level from message and returns structured explanation.
    Supports: eli5, beginner (default), advanced.
    """
    from tools import explain_topic

    msg_lower = message.lower()

    # Detect level
    if any(w in msg_lower for w in ["eli5", "like i'm 5", "like im 5", "simple", "easy", "kid"]):
        level = "eli5"
    elif any(w in msg_lower for w in ["advanced", "in depth", "deep", "detailed", "technical", "expert"]):
        level = "advanced"
    else:
        level = "beginner"

    # Extract topic
    topic = message
    for phrase in ["explain", "what is", "what are", "how does", "how do", "tell me about", "describe", "eli5"]:
        if phrase in msg_lower:
            topic = message[msg_lower.index(phrase) + len(phrase):].strip()
            break
    topic = topic.strip("?.,! ") or message

    # Add level toggle hint to response
    result = explain_topic(topic, level)
    result += f"\n\n💡 *Want a different level? Say \"explain {topic} like I'm 5\" or \"explain {topic} advanced\"*"
    return result


def progress_agent(message: str, session_id: str) -> str:
    from tools import get_progress
    progress_data = get_progress(session_id)
    system = """You are a study progress tracker for Study Buddy Bro.
Show the student their progress with encouragement.
Point out what subjects need more attention.
Suggest which topic to study next based on incomplete ones.
Keep it motivating and specific."""
    return call_gemini_with_system(system, f"{message}\n\nCurrent progress data:\n{progress_data}")


def reminder_agent(message: str) -> str:
    """
    Extracts time/email from message and confirms reminder setup.
    """
    system = """You are a study reminder assistant for Study Buddy Bro.
Help students set reminders for their study sessions and exams.
If the student mentions a time (e.g. "8pm", "tomorrow morning"), acknowledge it specifically.
If they mention an email, confirm you'll send to that address.
If no email is given, ask: "What email should I send the reminder to?"
If no time is given, ask: "What time should I remind you?"
Keep messages short, clear and encouraging.
End with a confirmation like: "✅ Got it! I'll remind you at [time] about [topic]." """
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

Respond as Study Buddy Bro — warm, helpful and encouraging.
Be conversational and student-focused. 📚"""

    msg_lower = user_message.lower()

    if any(w in msg_lower for w in ["quiz", "test me", "question", "mcq", "flashcard", "practice"]):
        return quiz_agent(user_message)

    elif any(w in msg_lower for w in ["explain", "what is", "what are", "how does", "how do", "tell me about", "understand", "definition", "eli5"]):
        return explainer_agent(user_message)

    elif any(w in msg_lower for w in ["exam", "schedule", "plan", "timetable", "days", "prepare", "calendar", "session"]):
        return schedule_agent(user_message, session_id)

    elif any(w in msg_lower for w in ["progress", "studied", "completed", "streak", "how much", "topics done"]):
        return progress_agent(user_message, session_id)

    elif any(w in msg_lower for w in ["remind", "reminder", "notify", "alert", "email"]):
        return reminder_agent(user_message)

    else:
        return call_gemini_with_system(routing_prompt, user_message)


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