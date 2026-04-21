import os
import uuid
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from dotenv import load_dotenv
from agent import run_agent_with_memory, get_conversation_history

load_dotenv()

app = FastAPI(title="Study Buddy Bro", version="1.0.0")


@app.get("/health")
async def health_check():
    return {
        "status": "running",
        "app": "Study Buddy Bro",
        "project": "study-buddy-bro-guide",
        "database": "study-buddy-datastore",
        "model": "gemini-2.5-flash (Vertex AI)",
        "agents": [
            "studybuddy_primary",
            "schedule_agent",
            "quiz_agent",
            "explainer_agent",
            "progress_agent",
            "reminder_agent"
        ]
    }


@app.post("/chat")
async def chat(request: Request):
    try:
        body         = await request.json()
        user_message = body.get("message", "").strip()
        session_id   = body.get("session_id", str(uuid.uuid4()))

        if not user_message:
            return JSONResponse(
                status_code=400,
                content={"error": "Message cannot be empty"}
            )

        loop  = asyncio.get_event_loop()
        reply = await loop.run_in_executor(
            None,
            run_agent_with_memory,
            session_id,
            user_message
        )

        # Check if quiz agent returned a JSON quiz signal
        if reply.startswith("QUIZ_JSON:"):
            topic = reply[len("QUIZ_JSON:"):].strip()
            from tools import generate_quiz_json
            quiz_data = await loop.run_in_executor(None, generate_quiz_json, topic, 5)
            return JSONResponse(content={
                "session_id": session_id,
                "reply": "",
                "quiz": quiz_data,
                "status": "success"
            })

        return JSONResponse(content={
            "session_id": session_id,
            "reply": reply,
            "status": "success"
        })

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "status": "failed"}
        )


@app.post("/quiz")
async def generate_quiz_endpoint(request: Request):
    """
    Dedicated quiz endpoint.
    Body: { "topic": "Photosynthesis", "num_questions": 5 }
    Returns: { "status": "success", "quiz": { "topic": ..., "questions": [...] } }
    """
    try:
        body          = await request.json()
        topic         = body.get("topic", "General Knowledge").strip()
        num_questions = int(body.get("num_questions", 5))
        num_questions = max(1, min(num_questions, 10))  # clamp between 1-10

        from tools import generate_quiz_json
        loop      = asyncio.get_event_loop()
        quiz_data = await loop.run_in_executor(None, generate_quiz_json, topic, num_questions)

        return JSONResponse(content={
            "status": "success",
            "quiz": quiz_data
        })

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "status": "failed"}
        )


@app.get("/history/{session_id}")
async def get_history(session_id: str):
    try:
        history = get_conversation_history(session_id)
        return JSONResponse(content={
            "session_id": session_id,
            "history": history,
            "count": len(history)
        })
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    try:
        with open("index.html", "r") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>Study Buddy Bro is running!</h1>"
                    "<a href='/docs'>API Docs</a>"
        )


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)