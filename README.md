# Assistente SIN v5.3

An AI-powered chatbot for power system engineers working with Brazil's **Sistema Interligado Nacional (SIN)**. It combines RAG-based Q&A over technical documents with a deterministic, step-by-step simulation guide for ANAREDE (CEPEL's power flow software).

---

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Application](#running-the-application)
- [Usage Guide](#usage-guide)
- [Admin Panel](#admin-panel)
- [Document Ingestion](#document-ingestion)
- [Version History](#version-history)

---

## Overview

Assistente SIN is a Streamlit-based conversational assistant designed for electrical engineers and power system planners in Brazil. It answers technical questions about the SIN using Retrieval-Augmented Generation (RAG) over indexed PDF documents (ONS reports, EPE plans, CEPEL manuals), and provides a structured simulation guide that walks users through BESS (Battery Energy Storage System) and STATCOM insertion studies in ANAREDE.

The system supports two LLM backends:
- **Google Gemini** (default) — cloud-based, no local GPU required
- **Ollama** (local) — fully offline, privacy-first option

---

## Key Features

| Feature | Description |
|---|---|
| **RAG Q&A** | Answers technical questions using indexed PDF documents from ONS, EPE, and CEPEL |
| **Simulation Guide** | 12-step deterministic state machine that guides BESS/STATCOM insertion in ANAREDE |
| **PWF Code Generation** | Auto-generates DBAR, DLIN, and DCER blocks for ANAREDE `.pwf` files |
| **Contingency Analysis** | Guides N-1 contingency setup and generates DCTG blocks |
| **Pause/Resume** | Pause simulation mid-step, ask free questions, resume later (even across sessions) |
| **User Authentication** | PostgreSQL-backed login/signup with access code gating |
| **Admin Panel** | Standalone dashboard with user management, session transcripts, flagging, and exports |
| **Chat Logging** | All conversations are logged with session tracking and simulation step metadata |
| **Dual LLM Support** | Switch between Gemini (cloud) and Ollama (local) via environment variable |

---

## Architecture

```
User Browser
    |
    v
+---------------------+        +---------------------+
| Streamlit App       |        | Admin App           |
| (app.py :8501)      |        | (admin_app.py :8503)|
+---------------------+        +---------------------+
    |        |                          |
    v        v                          v
+--------+ +------------------------+  |
| LLM    | | Simulation State       |  |
| Chain  | | Machine (_handle_sim)  |  |
+--------+ +------------------------+  |
    |                                   |
    v                                   v
+--------------------------------------------------+
|              PostgreSQL (:5433)                   |
|  Tables: users, chat_logs, sessions, documents   |
+--------------------------------------------------+
    |
    v
+--------------------------------------------------+
|              Qdrant (:6333)                       |
|  Collection: sin_docs (vector store)             |
+--------------------------------------------------+
```

### Component Roles

| Component | File(s) | Purpose |
|---|---|---|
| **Main App** | `app.py` | Streamlit UI, auth gate, chat loop, simulation state machine |
| **Admin App** | `admin_app.py` | Standalone Streamlit admin dashboard (separate port) |
| **Admin Panel** | `admin/panel.py` | Dashboard rendering: metrics, users, sessions, documents, exports |
| **Auth DB** | `auth/db.py` | PostgreSQL connection, schema initialization (4 tables) |
| **Auth Service** | `auth/auth_service.py` | Signup/login, user CRUD, chat logging, sessions, dashboard stats, pause/resume persistence |
| **RAG Chain** | `rag/chain.py` | LangChain pipeline: retriever + LLM + prompt template |
| **RAG Retriever** | `rag/retriever.py` | Qdrant vector similarity search |
| **RAG Ingestor** | `rag/ingestor.py` | PDF extraction + chunking + vector embedding into Qdrant |
| **Ingest API** | `ingest_api.py` | FastAPI endpoint for n8n webhook-triggered PDF ingestion |
| **System Prompt** | `prompts/system_prompt.py` | LLM system prompt with SIN domain knowledge |
| **Config** | `config/settings.py` | Centralized environment variable loading |
| **ANAREDE Lib** | `utils/anarede_lib.py` | Generates DBAR, DLIN, DCER, DCTG code blocks for `.pwf` files |
| **PWF Agent** | `agents/pwf_agent.py` | High-level PWF block generation (BESS, STATCOM, contingencies) |
| **Results Analyzer** | `agents/results_analyzer.py` | Convergence checking and results formatting |
| **Session Memory** | `memory/session_memory.py` | In-memory `StudyState` object for current session context |
| **Persistent Memory** | `memory/persistent_memory.py` | JSON file-based study state persistence |
| **File Utils** | `utils/file_utils.py`, `utils/pwf_handler.py` | File manipulation helpers |

---

## Project Structure

```
sin_chatbot/
├── app.py                    # Main Streamlit app (user-facing, port 8501)
├── admin_app.py              # Admin Streamlit app (port 8503)
├── ingest_api.py             # FastAPI ingest endpoint for n8n
├── requirements.txt          # Python dependencies
├── docker-compose.yml        # Qdrant + PostgreSQL
├── docker-compose.v3.yml     # Alternative compose (v3 config)
├── docker-compose.n8n.yml    # n8n workflow engine (optional)
├── .env.example              # Environment variable template
├── .env.v3                   # Active environment file (gitignored)
│
├── auth/                     # Authentication & database layer
│   ├── db.py                 #   Connection pool, schema init (users, chat_logs, sessions, documents)
│   └── auth_service.py       #   All auth, CRUD, logging, stats, pause/resume functions
│
├── admin/                    # Admin panel UI
│   └── panel.py              #   render_admin_panel() — 5 sections via sidebar radio
│
├── rag/                      # RAG pipeline
│   ├── chain.py              #   LangChain chain (Gemini or Ollama + Qdrant retriever)
│   ├── retriever.py          #   Vector similarity search against Qdrant
│   └── ingestor.py           #   PDF → chunks → embeddings → Qdrant
│
├── prompts/                  # LLM prompts
│   └── system_prompt.py      #   Domain-specific system prompt for the SIN assistant
│
├── agents/                   # Simulation agents
│   ├── pwf_agent.py          #   DBAR/DLIN/DCER/DCTG block generators
│   ├── anarede_guide.py      #   Simulation guide helpers
│   └── results_analyzer.py   #   Convergence check & results formatting
│
├── memory/                   # State management
│   ├── session_memory.py     #   StudyState dataclass (in-memory)
│   └── persistent_memory.py  #   JSON-based study persistence
│
├── config/                   # Configuration
│   └── settings.py           #   Loads all env vars with defaults
│
├── utils/                    # Utilities
│   ├── anarede_lib.py        #   ANAREDE PWF format library (DBAR, DLIN, DCER columns)
│   ├── file_utils.py         #   File I/O helpers
│   └── pwf_handler.py        #   PWF file parsing
│
├── docs/                     # PDF documents for RAG indexing
│   ├── incoming/             #   Drop zone for new PDFs
│   └── processed/            #   PDFs that have been indexed
│
├── memory_store/             # JSON persistence for study state
├── modified_pwf/             # Generated PWF modification files
├── results/                  # Simulation results storage
├── uploaded_pwf/             # User-uploaded PWF files
└── n8n_workflows/            # Exported n8n workflow definitions
```

---

## Prerequisites

| Requirement | Version | Purpose |
|---|---|---|
| **Python** | 3.10+ | Runtime for Streamlit and all backend code |
| **Docker** + **Docker Compose** | Latest | Runs Qdrant (vector DB) and PostgreSQL |
| **Ollama** (optional) | Latest | Local LLM inference (only if not using Gemini) |
| **Google API Key** (optional) | — | Required if using Gemini as the LLM provider |

---

## Installation

### Step 1: Clone the Repository

```bash
git clone <your-repo-url>
cd sin_chatbot
```

### Step 2: Create a Python Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate   # macOS/Linux
# or: venv\Scripts\activate  # Windows
```

### Step 3: Install Python Dependencies

```bash
pip install -r requirements.txt
```

The main dependencies are:
- `streamlit` — web UI framework
- `langchain`, `langchain-community`, `langchain-ollama`, `langchain-qdrant`, `langchain-google-genai` — RAG pipeline
- `google-generativeai` — Gemini API client
- `qdrant-client` — vector database client
- `pymupdf` — PDF text extraction
- `psycopg2-binary` — PostgreSQL driver
- `bcrypt` — password hashing
- `pandas` — data export in admin panel
- `fastapi`, `uvicorn` — ingest API server
- `sentence-transformers` — embedding models (Ollama fallback)
- `python-dotenv` — environment variable loading

### Step 4: Start Docker Services

```bash
docker-compose up -d
```

This starts:
- **Qdrant** on port `6333` (vector database for RAG)
- **PostgreSQL** on port `5433` (user auth, chat logs, sessions)

Verify containers are running:
```bash
docker ps
```

You should see `qdrant` and `sin_chatbot_postgres` containers.

### Step 5: Configure Environment Variables

```bash
cp .env.example .env.v3
```

Edit `.env.v3` with your settings:

```bash
# Choose your LLM provider: "gemini" or "ollama"
LLM_PROVIDER=gemini

# If using Gemini — paste your Google API key
GOOGLE_API_KEY=your_google_api_key_here
GEMINI_CHAT_MODEL=gemini-2.5-flash
GEMINI_EMBED_MODEL=models/gemini-embedding-001

# If using Ollama — ensure ollama is running locally
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_CHAT_MODEL=llama3.2
OLLAMA_EMBED_MODEL=nomic-embed-text

# Qdrant (match docker-compose.yml)
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_COLLECTION=sin_docs

# RAG tuning
CHUNK_SIZE=800
CHUNK_OVERLAP=100
TOP_K=5

# PostgreSQL (match docker-compose.yml)
POSTGRES_HOST=localhost
POSTGRES_PORT=5433
POSTGRES_USER=sinchatbot
POSTGRES_PASSWORD=changeme_in_env
POSTGRES_DB=sin_chatbot

# Access codes for user registration
ACCESS_CODE=SIN2026
ADMIN_ACCESS_CODE=GTA2026

# Paths
INCOMING_DOCS_DIR=docs/incoming
PROCESSED_DOCS_DIR=docs/processed
MODIFIED_PWF_DIR=modified_pwf
RESULTS_DIR=results
MEMORY_STORE_PATH=memory_store/last_study_v3.json
```

### Step 6: Set Up Ollama (only if using Ollama)

```bash
# Install Ollama (macOS)
brew install ollama

# Start the Ollama server
ollama serve

# Pull required models
ollama pull llama3.2
ollama pull nomic-embed-text
```

### Step 7: Index PDF Documents

Place your PDF documents in the `docs/` folder:
- ONS PAR/PEL reports
- EPE PDE documents
- CEPEL ANAREDE/ANATEM manuals
- Any other SIN-related technical documents

Then run the ingestor:

```bash
python -m rag.ingestor
```

This extracts text from all PDFs, splits into chunks, generates vector embeddings, and stores them in Qdrant.

---

## Configuration

### Environment File Priority

The application looks for environment files in this order:
1. `.env.v3` (preferred)
2. `.env` (fallback)

### LLM Provider Selection

Set `LLM_PROVIDER` in your env file:

| Value | Provider | Requirements |
|---|---|---|
| `gemini` | Google Gemini API | `GOOGLE_API_KEY` must be set. No local GPU needed. |
| `ollama` | Local Ollama | Ollama must be running. Models must be pulled. |

### Access Codes

Registration requires an access code to prevent unauthorized signups:

| Variable | Purpose | Default |
|---|---|---|
| `ACCESS_CODE` | Required for regular user signup | `SIN2026` |
| `ADMIN_ACCESS_CODE` | Required for admin account creation | `GTA2026` |

Change these in `.env.v3` to any value you prefer. Users must enter the correct code during registration.

---

## Running the Application

### User App (port 8501)

```bash
streamlit run app.py --server.port 8501
```

Open in browser: **http://localhost:8501**

### Admin App (port 8503)

```bash
streamlit run admin_app.py --server.port 8503
```

Open in browser: **http://localhost:8503**

### Run Both Simultaneously

```bash
streamlit run app.py --server.port 8501 &
streamlit run admin_app.py --server.port 8503 &
```

### Ingest API (optional, for n8n integration)

```bash
uvicorn ingest_api:app --port 8002
```

---

## Usage Guide

### Free Q&A Mode

By default, the chatbot operates in free conversation mode. Type any technical question about the SIN, power systems, ANAREDE, BESS, STATCOM, HVDC, etc. The assistant retrieves relevant context from indexed documents and generates an informed response.

### Simulation Guide Mode

To start a guided simulation, type a phrase like:
- "Quero simular"
- "Quero inserir um BESS"
- "Quero inserir um STATCOM"
- "Iniciar simulacao"

The assistant enters a 12-step guided workflow:

| Step | Description |
|---|---|
| **STEP 1** | Choose database: EPE (PDE) or ONS (PAR/PEL) |
| **STEP 2** | Select study year(s) (e.g., 2028, 2029) |
| **STEP 3** | Choose load scenario (6 for PAR/PEL, 8 for PDE) |
| **STEP 4** | Load SAV file in ANAREDE, verify convergence (green indicator) |
| **STEP 6** | Load or draw LST diagram for visualization |
| **STEP 7** | Specify insertion bus (BESS or STATCOM) |
| **STEP 8** | Configure BESS power: mode (PV/PQ), MVA, active power (MW) |
| **STEP 9** | Save the modified case in ANAREDE |
| **STEP 10** | Run power flow (Ctrl+R), check convergence |
| **STEP 11** | Analyze results (overloads, voltage violations) |
| **STEP 11B** | Optional N-1 contingency analysis |
| **STEP 12** | Next steps: repeat with different scenarios/years |

For STATCOM, the path diverges at STEP 7 with Q-limit and controlled bus configuration instead of BESS power config.

### Free Questions During Simulation

You can ask free technical questions at any point during the simulation (e.g., "O que e uma barra PV?"). The assistant answers via RAG and then shows a compact nudge to resume the simulation step.

### Pause/Resume Simulation (v5.3)

- **Pause via sidebar**: Click the "Pausar simulacao" button in the sidebar
- **Resume via sidebar**: Click the "Retomar" button when paused
- **Resume via text**: Type "retomar" or "continuar simulacao"
- **Auto-resume**: If you type a simulation-like answer while paused, the simulation resumes automatically
- **Cross-session resume**: If you log out while paused, the simulation state is saved to PostgreSQL. On next login, it is automatically restored.
- **Encerrar**: Click "Encerrar" in the sidebar or type "encerrar" at any time to end the simulation

### PWF Code Generation

The assistant automatically generates ANAREDE-compatible `.pwf` modification blocks:

- **DBAR**: Bus data for the new BESS/STATCOM bus
- **DLIN**: Transmission line connecting the new bus to the existing network
- **DCER**: Controlled shunt reactor data for STATCOM
- **DCTG**: Contingency definition blocks for N-1 analysis

These are displayed as copyable code blocks in the chat.

---

## Admin Panel

The admin panel runs as a separate Streamlit app on port 8503. It requires an admin account (created with `ADMIN_ACCESS_CODE`).

### Sections

| Section | Description |
|---|---|
| **Visao Geral** | Dashboard with key metrics: total users, new users this week, messages today/this week, daily message volume chart |
| **Usuarios** | User list with search, role management (promote/demote admin), user deletion |
| **Sessoes** | Session browser with filters (user, date, type, flagged). View full chat transcripts with message bubbles. Flag/unflag sessions with notes. |
| **Documentos** | Document tracking: uploaded files, chunk counts, Qdrant indexing status |
| **Exportar** | Export chat logs and session data as CSV or JSON |

### Creating an Admin Account

1. Open **http://localhost:8503**
2. Go to the "Criar conta admin" tab
3. Enter email, name, password, and the `ADMIN_ACCESS_CODE`
4. The account is created with `role = admin`

---

## Document Ingestion

### Manual Ingestion

```bash
# Place PDFs in docs/ folder
cp your_document.pdf docs/

# Run ingestor
python -m rag.ingestor
```

### Via Ingest API (for n8n automation)

```bash
# Start the ingest API
uvicorn ingest_api:app --port 8002

# The n8n webhook at /webhook/ingest-pdf accepts PDF uploads
# and triggers indexing into Qdrant
```

### Re-indexing

To re-index all documents, simply run the ingestor again. New documents are added to the existing Qdrant collection.

---

## Database Schema

PostgreSQL tables (auto-created on first run by `auth/db.py`):

| Table | Purpose | Key Columns |
|---|---|---|
| `users` | User accounts | `id`, `email`, `password_hash`, `full_name`, `role`, `verified` |
| `chat_logs` | Message history | `user_id`, `session_id`, `role`, `message`, `sim_step` |
| `sessions` | Session tracking | `user_id`, `sim_type`, `final_sim_step`, `flagged`, `flag_note`, `paused_state` |
| `documents` | Indexed documents | `filename`, `chunk_count`, `qdrant_status`, `uploaded_by` |

---

## Version History

| Version | Branch | Highlights |
|---|---|---|
| **v5.3** | `v5.3` | Pause/resume simulation controls with Postgres persistence, smart auto-resume, compact return nudges, cross-session state restoration |
| **v5.2** | `v5.2` | Standalone admin panel (port 8503), access code gating for signup, separate admin access code |
| **v5.1** | `v5.1` | PostgreSQL-backed user authentication (login/signup), admin panel |
| **v5.0** | `v5.0` | DCER/STATCOM support, contingency guide, non-convergence troubleshooting, simulation context persistence, DBAR/DLIN bug fixes |

---

## Troubleshooting

### Qdrant connection error

```
Nao foi possivel conectar ao Qdrant ou Ollama
```

- Verify Qdrant is running: `docker ps | grep qdrant`
- If not running: `docker-compose up -d`
- Check port 6333 is not used by another service: `lsof -i :6333`

### PostgreSQL connection error

```
Banco de dados indisponivel
```

- Verify PostgreSQL is running: `docker ps | grep postgres`
- If not running: `docker-compose up -d`
- Check credentials match `.env.v3`

### Ollama model not found

```bash
# Pull required models
ollama pull llama3.2
ollama pull nomic-embed-text

# Verify models are available
ollama list
```

### Port already in use

```bash
# Find and kill the process using the port
lsof -ti:8501 | xargs kill -9

# Then restart
streamlit run app.py --server.port 8501
```

---

## License

Internal project. All rights reserved.
