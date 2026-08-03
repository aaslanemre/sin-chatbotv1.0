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
            verified BOOLEAN DEFAULT false,
            created_at TIMESTAMP DEFAULT now(),
            last_login TIMESTAMP,
            verification_token TEXT,
            verification_sent_at TIMESTAMP
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
    # Flip default verified to false for new installs (existing rows unaffected)
    cur.execute("""
        ALTER TABLE users ALTER COLUMN verified SET DEFAULT false;
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
            flag_note TEXT
        );
    """)
    conn.commit()
    cur.close()
    conn.close()
