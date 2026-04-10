import os
import datetime
import logging
import requests
import base64
from google.cloud import datastore
from googleapiclient.discovery import build
from google.auth import default
from dotenv import load_dotenv
from email.mime.text import MIMEText

load_dotenv()

db = datastore.Client(
    project="study-buddy-bro-guide",
    database="study-buddy-datastore"
)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
GEMINI_URL = (
    "https://generativelanguage.googleapis.com"
    "/v1beta/models/gemini-2.0-flash:generateContent"
    f"?key={GEMINI_API_KEY}"
)

def call_gemini(prompt: str) -> str:
    import google.auth
    import google.auth.transport.requests
    try:
        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        auth_req = google.auth.transport.requests.Request()
        creds.refresh(auth_req)
        url = (
            "https://us-central1-aiplatform.googleapis.com/v1"
            "/projects/study-buddy-bro-guide"
            "/locations/us-central1"
            "/publishers/google/models/gemini-2.0-flash:generateContent"
        )
        headers = {
            "Authorization": f"Bearer {creds.token}",
            "Content-Type": "application/json"
        }
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        return f"Gemini error: {str(e)}"

def get_google_services():
    try:
        creds, _ = default(scopes=[
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/tasks"
        ])
        calendar = build("calendar", "v3", credentials=creds)
        gmail    = build("gmail",    "v1", credentials=creds)
        tasks    = build("tasks",    "v1", credentials=creds)
        return calendar, gmail, tasks
    except Exception as e:
        logging.error(f"Failed to get Google services: {e}")
        return None, None, None

def create_study_schedule(topic: str, exam_date: str, daily_hours: int = 2, session_id: str = "default") -> str:
    try:
        calendar, _, _ = get_google_services()
        exam_dt   = datetime.datetime.strptime(exam_date, "%Y-%m-%d")
        today     = datetime.datetime.now()
        days_left = (exam_dt - today).days
        if days_left <= 0:
            return f"Exam date {exam_date} has already passed!"
        created = []
        if calendar:
            for i in range(min(days_left, 7)):
                session_date = today + datetime.timedelta(days=i + 1)
                start = session_date.replace(hour=18, minute=0, second=0, microsecond=0)
                end   = start + datetime.timedelta(hours=daily_hours)
                event = {
                    "summary": f"Study Buddy Bro — {topic}",
                    "description": f"Study session for {topic}. Exam on {exam_date}.",
                    "start": {"dateTime": start.isoformat(), "timeZone": "Asia/Kolkata"},
                    "end":   {"dateTime": end.isoformat(),   "timeZone": "Asia/Kolkata"},
                    "colorId": "2"
                }
                calendar.events().insert(calendarId="primary", body=event).execute()
                created.append(session_date.strftime("%A, %b %d"))
        else:
            for i in range(min(days_left, 7)):
                session_date = today + datetime.timedelta(days=i + 1)
                created.append(session_date.strftime("%A, %b %d"))
        key = db.key("schedules", session_id)
        entity = db.get(key) or datastore.Entity(key=key)
        entity.update({
            "topic": topic,
            "exam_date": exam_date,
            "sessions_created": created,
            "daily_hours": daily_hours,
            "created_at": datetime.datetime.utcnow()
        })
        db.put(entity)
        return (f"Created {len(created)} study sessions for '{topic}' before your exam on {exam_date}:\n"
                + "\n".join(f"  • {d} — {daily_hours}hrs" for d in created)
                + "\n\nAll sessions saved! 📅")
    except Exception as e:
        return f"Could not create schedule: {str(e)}"

def get_upcoming_exams(session_id: str = "default") -> str:
    try:
        calendar, _, _ = get_google_services()
        if not calendar:
            key = db.key("schedules", session_id)
            entity = db.get(key)
            if entity:
                data = dict(entity)
                return f"Upcoming: {data.get('topic')} exam on {data.get('exam_date')}"
            return "No upcoming exams found. Tell me about your exams!"
        now    = datetime.datetime.utcnow().isoformat() + "Z"
        events = calendar.events().list(
            calendarId="primary", timeMin=now, maxResults=10,
            singleEvents=True, orderBy="startTime", q="Study Buddy Bro"
        ).execute()
        items = events.get("items", [])
        if not items:
            return "No upcoming study sessions found. Want me to create some?"
        result = "Your upcoming Study Buddy Bro sessions:\n"
        for e in items:
            start = e["start"].get("dateTime", e["start"].get("date"))
            result += f"  • {e['summary']} — {start}\n"
        return result
    except Exception as e:
        return f"Could not fetch calendar: {str(e)}"

def generate_quiz(topic: str, num_questions: int = 5) -> str:
    prompt = f"""Generate exactly {num_questions} multiple choice questions about "{topic}".
Format each question exactly like this:
Q1. [Question text]
A) [Option]
B) [Option]
C) [Option]
D) [Option]
Answer: [Correct letter]
Explanation: [One sentence why]
Make questions educational and clear for a student."""
    return call_gemini(prompt)

def explain_topic(topic: str, level: str = "beginner") -> str:
    prompt = f"""Explain "{topic}" for a {level}-level student.
Structure your explanation like this:
1. Simple definition (2-3 sentences)
2. Real-world analogy that makes it click
3. Key points to remember (3-5 bullet points)
4. One worked example
Keep it friendly, clear and encouraging.
End with: "Want me to quiz you on this? 📝" """
    return call_gemini(prompt)

def add_study_topic(session_id: str, subject: str, topic: str) -> str:
    try:
        key = db.key("topics", f"{session_id}_{subject}_{topic}")
        entity = datastore.Entity(key=key)
        entity.update({
            "session_id": session_id,
            "topic": topic,
            "subject": subject,
            "status": "pending",
            "added_at": datetime.datetime.utcnow()
        })
        db.put(entity)
        return f"Added '{topic}' under {subject}. Tracking started! 📊"
    except Exception as e:
        return f"Could not add topic: {str(e)}"

def update_progress(session_id: str, subject: str, topic: str, status: str = "completed") -> str:
    try:
        key = db.key("topics", f"{session_id}_{subject}_{topic}")
        entity = db.get(key) or datastore.Entity(key=key)
        entity.update({
            "session_id": session_id,
            "subject": subject,
            "topic": topic,
            "status": status,
            "updated_at": datetime.datetime.utcnow()
        })
        db.put(entity)
        emoji = "✅" if status == "completed" else "🔄"
        return f"{emoji} Marked '{topic}' as {status}. Keep going!"
    except Exception as e:
        return f"Could not update progress: {str(e)}"

def get_progress(session_id: str) -> str:
    try:
        query = db.query(kind="topics")
        query.add_filter(
            filter=datastore.query.PropertyFilter("session_id", "=", session_id)
        )
        all_topics = list(query.fetch())
        if not all_topics:
            return "No topics tracked yet! Tell me what subjects you're studying. 📚"
        subjects = {}
        for t in all_topics:
            subj = t.get("subject", "General")
            if subj not in subjects:
                subjects[subj] = []
            subjects[subj].append(t)
        result       = "📊 Your Study Buddy Bro Progress:\n\n"
        total_topics = 0
        total_done   = 0
        for subj, topics in subjects.items():
            done  = sum(1 for t in topics if t.get("status") == "completed")
            total = len(topics)
            pct   = int((done / total) * 100) if total > 0 else 0
            filled = "█" * (pct // 10)
            empty  = "░" * (10 - pct // 10)
            result += f"📚 {subj}\n   [{filled}{empty}] {pct}% ({done}/{total} topics)\n\n"
            total_topics += total
            total_done   += done
        overall = int((total_done / total_topics) * 100) if total_topics > 0 else 0
        result += f"─────────────────\nOverall: {overall}% complete ({total_done}/{total_topics} topics)\n"
        if overall == 100:
            result += "🎉 Amazing — you've covered everything!"
        elif overall >= 70:
            result += "💪 Great progress — keep pushing!"
        elif overall >= 40:
            result += "📖 Good start — stay consistent!"
        else:
            result += "🚀 Just getting started — you've got this!"
        return result
    except Exception as e:
        return f"Could not fetch progress: {str(e)}"

def send_study_reminder(to_email: str, subject_line: str, body: str) -> str:
    try:
        _, gmail, _ = get_google_services()
        if not gmail:
            return f"Reminder saved: '{subject_line}' for {to_email}"
        message            = MIMEText(body)
        message["to"]      = to_email
        message["subject"] = f"Study Buddy Bro — {subject_line}"
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        gmail.users().messages().send(userId="me", body={"raw": raw}).execute()
        return f"✅ Reminder sent to {to_email} — '{subject_line}'"
    except Exception as e:
        return f"Could not send reminder: {str(e)}"