import os
from pathlib import Path
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

for env_file in ['.env.v3', '.env']:
    if Path(env_file).exists():
        load_dotenv(env_file, override=True)
        break


def get_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5433")),
        user=os.getenv("POSTGRES_USER", "sinchatbot"),
        password=os.getenv("POSTGRES_PASSWORD", "changeme_in_env"),
        dbname=os.getenv("POSTGRES_DB", "sin_chatbot"),
    )


def get_cursor(conn):
    return conn.cursor(cursor_factory=RealDictCursor)


def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT,
            role TEXT DEFAULT 'user',
            verified BOOLEAN DEFAULT true,
            created_at TIMESTAMP DEFAULT now(),
            last_login TIMESTAMP,
            verification_token TEXT,      -- deprecated: kept for schema compat
            verification_sent_at TIMESTAMP -- deprecated: kept for schema compat
        );
    """)
    # Add new columns if upgrading from v5.1
    for col, coltype in [
        ("verification_token", "TEXT"),
        ("verification_sent_at", "TIMESTAMP"),
    ]:
        cur.execute(f"""
            DO $$ BEGIN
                ALTER TABLE users ADD COLUMN {col} {coltype};
            EXCEPTION WHEN duplicate_column THEN NULL;
            END $$;
        """)
    # Access-code flow: all signups are verified=true immediately
    cur.execute("""
        ALTER TABLE users ALTER COLUMN verified SET DEFAULT true;
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS chat_logs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID REFERENCES users(id),
            session_id UUID NOT NULL,
            role TEXT NOT NULL,
            message TEXT NOT NULL,
            sim_step TEXT,
            created_at TIMESTAMP DEFAULT now()
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            filename TEXT NOT NULL,
            uploaded_by UUID REFERENCES users(id),
            chunk_count INTEGER DEFAULT 0,
            qdrant_status TEXT DEFAULT 'processing',
            uploaded_at TIMESTAMP DEFAULT now()
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID REFERENCES users(id),
            started_at TIMESTAMP DEFAULT now(),
            last_message_at TIMESTAMP DEFAULT now(),
            message_count INTEGER DEFAULT 0,
            sim_type TEXT,
            final_sim_step TEXT,
            flagged BOOLEAN DEFAULT false,
            flag_note TEXT,
            paused_state JSONB
        );
    """)
    # Add paused_state column if upgrading from v5.2
    cur.execute("""
        DO $$ BEGIN
            ALTER TABLE sessions ADD COLUMN paused_state JSONB;
        EXCEPTION WHEN duplicate_column THEN NULL;
        END $$;
    """)
    # v6.4.0 — additive only: link chat rows to messages and record sim type
    cur.execute("ALTER TABLE chat_logs ADD COLUMN IF NOT EXISTS message_id TEXT;")
    cur.execute("ALTER TABLE chat_logs ADD COLUMN IF NOT EXISTS sim_type TEXT;")
    # v6.4.1 — grounding confidence snapshot (additive; old rows stay NULL)
    cur.execute("ALTER TABLE chat_logs ADD COLUMN IF NOT EXISTS grounding_score REAL;")
    cur.execute("ALTER TABLE chat_logs ADD COLUMN IF NOT EXISTS grounding_level TEXT;")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID REFERENCES users(id),
            session_id UUID,
            message_id TEXT,
            rating TEXT,                 -- 'up' | 'down'
            category TEXT,               -- tecnico | passo | faltou | formato | outro
            comment TEXT,
            assistant_message TEXT,      -- snapshot
            user_message TEXT,           -- snapshot of the triggering message
            sim_type TEXT,               -- BESS | STATCOM | NETWORK | NULL
            sim_step_before TEXT,
            sim_step_after TEXT,
            app_version TEXT,
            status TEXT DEFAULT 'novo',  -- novo | em_analise | resolvido | descartado
            admin_note TEXT,
            created_at TIMESTAMP DEFAULT now(),
            updated_at TIMESTAMP DEFAULT now(),
            UNIQUE (user_id, message_id)
        );
    """)
    cur.execute("ALTER TABLE feedback ADD COLUMN IF NOT EXISTS grounding_score REAL;")
    cur.execute("ALTER TABLE feedback ADD COLUMN IF NOT EXISTS grounding_level TEXT;")
    # v6.5.0 — "Novidades da versão" banner (additive; NULL = never dismissed)
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen_version TEXT;")
    # v6.5.0 — beginner/expert mode per user and how each user message was entered
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS ui_mode TEXT DEFAULT 'iniciante';")
    cur.execute("ALTER TABLE chat_logs ADD COLUMN IF NOT EXISTS input_source TEXT;")  # typed | button | form
    conn.commit()
    cur.close()
    conn.close()
