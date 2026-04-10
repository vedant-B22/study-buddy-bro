import os
import datetime
import asyncio
import logging
import nest_asyncio
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import FunctionTool
from google.cloud import datastore
from google.genai import types
from dotenv import load_dotenv
from tools import (
    create_study_schedule, get_upcoming_exams,
    generate_quiz, explain_topic, send_study_reminder,
    get_progress, update_progress, add_study_topic
)

nest_asyncio.apply()
load_dotenv()

os.environ["GOOGLE_API_KEY"] = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")

db = datastore.Client(
    project="study-buddy-bro-guide",
    database="study-buddy-datastore"
)

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
        logging.error(f"Failed to save conversation: {e}")

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
        logging.error(f"Failed to get history: {e}")
        return []

def save_student_profile(session_id: str, data: dict):
    try:
        key = db.key("students", session_id)
        entity = db.get(key) or datastore.Entity(key=key)
        entity.update(data)
        db.put(entity)
    except Exception as e:
        logging.error(f"Failed to save profile: {e}")

def get_student_profile(session_id: str) -> dict:
    try:
        key = db.key("students", session_id)
        entity = db.get(key)
        return dict(entity) if entity else {}
    except Exception as e:
        return {}

schedule_agent = Agent(
    name="schedule_agent",
    model="gemini-2.0-flash",
    description="Handles study scheduling, exam tracking and calendar management.",
    instruction="""You are a study schedule manager for Study Buddy Bro.
    Create study sessions on Google Calendar, retrieve upcoming exams,
    and suggest how to split study time. Be encouraging and realistic.""",
    tools=[FunctionTool(create_study_schedule), FunctionTool(get_upcoming_exams)]
)

quiz_agent = Agent(
    name="quiz_agent",
    model="gemini-2.0-flash",
    description="Generates quizzes, MCQs and flashcards for any study topic.",
    instruction="""You are a quiz generator for Study Buddy Bro.
    Generate MCQ questions with 4 options and correct answers.
    Create clear, accurate questions matched to the student's topic.""",
    tools=[FunctionTool(generate_quiz)]
)

explainer_agent = Agent(
    name="explainer_agent",
    model="gemini-2.0-flash",
    description="Explains any academic topic in simple language.",
    instruction="""You are a patient tutor for Study Buddy Bro.
    Break down complex topics into simple explanations with analogies
    and real-world examples. Always check if the student understood.""",
    tools=[FunctionTool(explain_topic)]
)

progress_agent = Agent(
    name="progress_agent",
    model="gemini-2.0-flash",
    description="Tracks study progress, completed topics and study streaks.",
    instruction="""You are a study progress tracker for Study Buddy Bro.
    Track topics studied, show completion percentage per subject,
    maintain study streaks and motivate the student.""",
    tools=[FunctionTool(get_progress), FunctionTool(update_progress), FunctionTool(add_study_topic)]
)

reminder_agent = Agent(
    name="reminder_agent",
    model="gemini-2.0-flash",
    description="Sends email reminders for exams and study summaries.",
    instruction="""You are a study reminder assistant for Study Buddy Bro.
    Send email reminders for upcoming exams and pending topics.
    Keep messages short, clear and motivating.""",
    tools=[FunctionTool(send_study_reminder)]
)

primary_agent = Agent(
    name="studybuddy_primary",
    model="gemini-2.0-flash",
    description="Primary Study Buddy Bro agent that routes requests to sub-agents.",
    instruction="""You are Study Buddy Bro — a friendly AI study assistant.
    You coordinate 5 specialized agents:
    - schedule_agent: study plans, exams, calendar, timetables
    - quiz_agent: MCQs, flashcards, practice questions
    - explainer_agent: understanding topics, concepts, explanations
    - progress_agent: tracking completed topics, study streaks
    - reminder_agent: email reminders and notifications

    When a student messages you:
    1. Understand their intent
    2. Route to correct sub-agent (or multiple if needed)
    3. Combine responses into one friendly reply
    4. End with an encouraging message or next step

    Examples:
    - "I have a math exam in 2 days" → schedule_agent + reminder_agent
    - "Explain photosynthesis" → explainer_agent
    - "Quiz me on Python" → quiz_agent
    - "What have I studied?" → progress_agent

    Always be warm, supportive and student-friendly.""",
    sub_agents=[schedule_agent, quiz_agent, explainer_agent, progress_agent, reminder_agent]
)

def get_agent():
    return primary_agent

async def _run_agent_async(session_id: str, full_message: str) -> str:
    svc = InMemorySessionService()
    r = Runner(
        agent=primary_agent,
        app_name="study-buddy-bro",
        session_service=svc
    )
    await svc.create_session(
        app_name="study-buddy-bro",
        user_id="user",
        session_id=session_id
    )
    content = types.Content(
        role="user",
        parts=[types.Part(text=full_message)]
    )
    result = "I'm here to help! What are you studying today? 📚"
    async for event in r.run_async(
        user_id="user",
        session_id=session_id,
        new_message=content
    ):
        if hasattr(event, 'is_final_response') and event.is_final_response():
            if hasattr(event, 'content') and event.content:
                for part in event.content.parts:
                    if hasattr(part, 'text') and part.text:
                        result = part.text
                        break
    return result

def run_agent_with_memory(session_id: str, user_message: str) -> str:
    save_conversation(session_id, "user", user_message)
    history = get_conversation_history(session_id)

    context = ""
    if history:
        context = "Previous conversation:\n"
        for h in history:
            context += f"{h['role'].upper()}: {h['message']}\n"
        context += "\nCurrent message: "
    full_message = context + user_message

    reply = "I'm here to help! What are you studying today? 📚"
    try:
        loop = asyncio.get_event_loop()
        reply = loop.run_until_complete(_run_agent_async(session_id, full_message))
    except Exception as e:
        reply = f"Agent error: {str(e)}"

    save_conversation(session_id, "assistant", reply)
    save_student_profile(session_id, {
        "last_active": datetime.datetime.utcnow(),
        "session_id": session_id
    })
    return reply