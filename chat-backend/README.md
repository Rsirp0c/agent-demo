# Chat Backend

A FastAPI backend for a multi-round AI chatbot using Azure OpenAI.

## Setup

Mac
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Windows
```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

The server will start at http://localhost:8000



## API Endpoints

### POST /api/chat
Send messages to the AI and get responses.
