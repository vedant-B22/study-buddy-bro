# 📚 Study Buddy Bro

> Your personal AI-powered multi-agent study assistant — built with Google ADK, Gemini & Firestore.

---

## 🚀 What is Study Buddy Bro?

Study Buddy Bro is an intelligent study assistant that uses multiple AI agents to help students learn smarter. It can create study schedules, quiz you on topics, explain concepts, track your progress, and send exam reminders.

---

## 🤖 Agents

| Agent | Role |
|---|---|
| 🧠 Primary Agent | Understands your query and routes to the right agent |
| 📅 Schedule Agent | Creates personalized study schedules |
| ❓ Quiz Agent | Generates quizzes on any topic |
| 💡 Explainer Agent | Explains concepts in simple language |
| 📊 Progress Agent | Tracks what you've studied |
| 🔔 Reminder Agent | Sends exam reminders via email |

---

## 🛠️ Tech Stack

- **Google ADK** — Multi-agent orchestration
- **Gemini 1.5 Flash** — LLM powering all agents
- **FastAPI** — Backend REST API
- **Google Cloud Firestore** — Conversation memory & storage
- **Google Cloud Run** — Deployment
- **Python** — Core language

---

## ⚙️ How to Run Locally

### 1. Clone the repo
```bash
git clone https://github.com/vedant-B22/study-buddy-bro.git
cd study-buddy-bro
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Set up environment variables
Create a `.env` file in the root folder:
GOOGLE_API_KEY=your_google_api_key
PROJECT_ID=your_gcp_project_id
GOOGLE_CLOUD_PROJECT=your_gcp_project_id
FIRESTORE_DATABASE=your_firestore_database
MODEL=gemini-1.5-flash
APP_NAME=Study Buddy Bro

### 4. Run the app
```bash
python main.py
```

Visit `http://localhost:8080` in your browser.

---

## 📡 API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/` | Frontend UI |
| GET | `/health` | Health check |
| POST | `/chat` | Send a message to the agent |
| GET | `/history/{session_id}` | Get conversation history |

---

## 💬 Example Usage

Send a POST request to `/chat`:
```json
{
  "message": "I have an exam in 3 days, help me make a study plan",
  "session_id": "user123"
}
```

---

## 🏗️ Project Structure
study-buddy-bro/
├── main.py          # FastAPI app entry point
├── agent.py         # Multi-agent logic
├── tools.py         # Agent tools
├── index.html       # Frontend UI
├── requirements.txt # Dependencies
├── Procfile         # Cloud Run startup command
└── .env             # Environment variables (not committed)

---

## 👨‍💻 Built By

**Vedant Baviskar** — Built for a Hackathon 🏆

---

## 📄 License

MIT License
