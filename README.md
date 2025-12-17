# 🎙️ Speech-to-Text Dashboard
### Django + Celery + Multiple AI STT Services

A full-featured **Speech-to-Text web application** built with **Django** and **Celery**.
Users can upload audio files, process them asynchronously using multiple AI engines, and download clean transcripts in TXT, Word, or PDF formats.

The system enforces a **per-user processing queue**, ensuring that only one transcription job runs at a time for each user.

---

## ✨ Features

- ✅ User authentication (Signup / Login)
- ✅ Asynchronous audio processing with **Celery**
- ✅ **Per-user queue system** (one active job per user)
- ✅ Multiple Speech-to-Text engines:
  - **EBOO**
  - **SCRIBE (MetisAI)**
  - **VIRA (Avanegar)**
- ✅ AJAX-based dashboard with live polling
- ✅ Export transcripts as:
  - TXT
  - DOCX (Word)
  - PDF (RTL & Persian-friendly)
- ✅ Safe delete logic (Windows-compatible, no SIGKILL)
- ✅ Clean and compact table UI

---

## 🧠 Application Workflow

1. User logs into the dashboard
2. Audio file is uploaded
3. File is saved in database with status **PENDING**
4. If the user has no active job:
   - Celery task starts immediately
   - Status → **PROCESSING**
5. AI service processes the audio
6. Result is saved:
   - **COMPLETED** → transcript available
   - **FAILED** → error message stored
7. Next pending file for the same user starts automatically

---

## 🔁 Per-User Queue Logic

- Each user can have **only one active transcription**
- Extra uploads are queued as `PENDING`
- When a task finishes, the next pending file starts automatically

Implemented in:
- `core/tasks.py → process_audio_file`

---

## 🛠️ Tech Stack

**Backend**
- Python 3.10+
- Django 5.x

**Async Processing**
- Celery
- Redis (broker + result backend)

**Frontend**
- Django Templates
- AJAX polling (no WebSockets)

**Database**
- PostgreSQL (production-ready)
- SQLite (optional for development)

**AI Services**
- REST-based external STT APIs

**OS Compatibility**
- ✅ Windows
- ✅ Linux

---

## 📁 Project Structure
```text
config/
├── settings.py        # Django + env + Celery config
├── urls.py
├── celery.py

core/
├── models.py          # AudioFile model + statuses
├── views.py           # Dashboard, upload, delete, download
├── tasks.py           # Celery tasks + queue logic
├── services.py        # EBOO / SCRIBE / VIRA integrations
├── forms.py
├── urls.py
├── templates/
│   ├── core/
│   │   ├── dashboard.html
│   │   └── landing.html
│   └── partials/
│       ├── file_table_container.html
│       └── row.html


🐍 Virtual Environment Setup (Required)
This project must be run inside a Python virtual environment.

✅ Windows

powershell


python -m venv venv
venv\Scripts\activate
✅ Linux / macOS

bash


python3 -m venv venv
source venv/bin/activate
Upgrade pip and install dependencies:


bash


pip install --upgrade pip
pip install -r requirements.txt
🔐 Environment Variables (.env)
Sensitive configuration values are stored in a .env file and loaded using python-dotenv.

Create a .env file in the project root:


env
# AI Service Tokens
EBOO_TOKEN=your_eboo_api_token
SCRIBE_TOKEN=your_metisai_token
VIRA_TOKEN=your_avanegar_token

📌 The .env file must be listed in .gitignore.

⚙️ Settings Integration
Environment variables are loaded automatically in config/settings.py:


python


from dotenv import load_dotenv
import os

load_dotenv()

EBOO_TOKEN = os.getenv("EBOO_TOKEN")
SCRIBE_TOKEN = os.getenv("SCRIBE_TOKEN")
VIRA_TOKEN = os.getenv("VIRA_TOKEN")
✅ No API keys are hardcoded.

🗄️ Database Setup
PostgreSQL configuration example (already used in project):


python


DATABASES = {
'default': {
'ENGINE': 'django.db.backends.postgresql',
'NAME': 'stt_db',
'USER': 'stt_user',
'PASSWORD': 'password',
'HOST': 'localhost',
'PORT': '5433',
}
}
Apply migrations:


bash


python manage.py migrate
🚦 Redis & Celery
Start Redis

bash


redis-server
Run Celery Worker

bash


celery -A config worker -l info
Make sure Redis is running before starting Celery.

▶️ Run Django Server

bash


python manage.py runserver
Then open:


http://127.0.0.1:8000/

