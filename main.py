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
        "model": "gemini-2.5-flash (Vertex AI)",   # ✅ Updated
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