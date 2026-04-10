import os
import datetime
import logging
import requests
import nest_asyncio
from google.cloud import datastore
from dotenv import load_dotenv

nest_asyncio.apply()
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
GEMINI_URL = (
    "https://generativelanguage.googleapis.com"
    "/v1beta/models/gemini-2.0-flash:generateContent"
    f"?key={GEMINI_API_KEY}"
)

db = datastore.Client(
    project="study-buddy-bro-guide",
    database="study-buddy-datastore"
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
# CORE GEMINI CALL
# ─────────────────────────────────────────
def call_gemini_with_system(system_prompt: str, user_message: str) -> str:
    try:
        payload = {
            "system_instruction": {
                "parts": [{"text": system_prompt}]
            },
            "contents": [{
                "role": "user",
                "parts": [{"text": user_message}]
            }]
        }
        r = requests.post(GEMINI_URL, json=payload, timeout=60)
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        return f"Agent error: {str(e)}"

# ─────────────────────────────────────────
# SUB-AGENTS — each is a function that
# calls Gemini with a specialized prompt
# ─────────────────────────────────────────
def schedule_agent(message: str, session_id: str) -> str:
    from tools import create_study_schedule, get_upcoming_exams
    system = """You are a study schedule manager for Study Buddy Bro.
    Help students plan their study sessions and track exam dates.
    Be encouraging, realistic and specific about dates and times.
    When the student mentions an exam, suggest a study plan with specific days."""
    return call_gemini_with_system(system, message)

def quiz_agent(message: str) -> str:
    from tools import generate_quiz
    # Extract topic from message and generate quiz
    system = """You are a quiz generator for Study Buddy Bro.
    Generate MCQ questions with 4 options (A, B, C, D) and correct answers.
    Always include explanations. Make questions educational and clear."""
    return call_gemini_with_system(system, message)

def explainer_agent(message: str) -> str:
    from tools import explain_topic
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
    # Build conversation context
    context = ""
    if history:
        context = "Previous conversation:\n"
        for h in history[-5:]:
            context += f"{h['role'].upper()}: {h['message']}\n"
        context += "\n"

    # Step 1: Ask Gemini to identify intent
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

    full_message = context + f"Student: {user_message}"
    
    # Route to appropriate sub-agent based on keywords
    msg_lower = user_message.lower()
    
    responses = []
    
    # Check for quiz intent
    if any(w in msg_lower for w in ["quiz", "test me", "question", "mcq", "flashcard", "practice"]):
        responses.append(quiz_agent(user_message))
    
    # Check for explanation intent
    elif any(w in msg_lower for w in ["explain", "what is", "what are", "how does", "tell me about", "understand", "definition"]):
        responses.append(explainer_agent(user_message))
    
    # Check for schedule intent
    elif any(w in msg_lower for w in ["exam", "schedule", "plan", "timetable", "days", "prepare", "calendar", "session"]):
        responses.append(schedule_agent(user_message, session_id))
    
    # Check for progress intent
    elif any(w in msg_lower for w in ["progress", "studied", "completed", "streak", "how much", "topics done"]):
        responses.append(progress_agent(user_message, session_id))
    
    # Check for reminder intent
    elif any(w in msg_lower for w in ["remind", "reminder", "notify", "alert", "email"]):
        responses.append(reminder_agent(user_message))
    
    # Default — use primary agent with full context
    else:
        responses.append(call_gemini_with_system(routing_prompt, user_message))
    
    return "\n\n".join(responses)

# ─────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────
def run_agent_with_memory(session_id: str, user_message: str) -> str:
    # Save user message
    save_conversation(session_id, "user", user_message)
    
    # Get history
    history = get_conversation_history(session_id)
    
    # Run primary agent
    try:
        reply = run_primary_agent(session_id, user_message, history)
    except Exception as e:
        reply = f"Sorry, something went wrong: {str(e)} — Please try again! 😅"
    
    # Save reply
    save_conversation(session_id, "assistant", reply)
    save_student_profile(session_id, {
        "last_active": datetime.datetime.utcnow(),
        "session_id": session_id
    })
    
    return reply

def get_agent():
    return None
