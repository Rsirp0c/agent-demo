# Azure OpenAI Chatbot Demo

This repository contains a FastAPI backend and a React user interface that together implement a multi-round chatbot powered by Azure OpenAI services.

## Overview
- **Backend (`chat-backend/`)** – FastAPI application exposing endpoints for the chatbot. It uses Azure OpenAI to process messages and can call helper tools.
- **Frontend (`chat-ui/`)** – React application providing a simple chat UI. It communicates with the backend to display assistant responses.

## Repository Structure
- `chat-backend/main.py` – FastAPI server entry point.
- `chat-backend/tools.py` – Azure utility functions used by the chatbot.
- `chat-ui/src/App.tsx` – Main React component for the chat interface.

## Prerequisites
- Python 3
- Node.js
- Azure credentials placed in a `.env` file with variables:
  - `AZURE_OPENAI_API_KEY`
  - `AZURE_OPENAI_ENDPOINT`
  - `AZURE_OPENAI_MODEL_NAME`
  - `AZURE_SUBSCRIPTION_ID`

## Setup

### Backend
1. `cd chat-backend`
2. Create and activate a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows use: venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Ensure the environment variables above are available (e.g., via the `.env` file).
5. Run the development server:
   ```bash
   uvicorn main:app --reload
   ```
   The API will be available at [http://localhost:8000](http://localhost:8000).

### Frontend
1. `cd chat-ui`
2. Install packages:
   ```bash
   npm install
   ```
3. Start the dev server:
   ```bash
   npm run dev
   ```
   The UI will open at [http://localhost:5173](http://localhost:5173).

## Usage
Visit [http://localhost:5173](http://localhost:5173) after both servers start. The frontend communicates with the FastAPI backend running on port 8000.

For more details see the READMEs in `chat-backend/` and `chat-ui/`.
