import json
import os
import bcrypt
from datetime import datetime
from auth.db import get_connection, get_cursor


# ── Auth ─────────────────────────────────────────────────────────────────────

def signup(email: str, password: str, full_name: str, access_code: str) -> dict:
    expected_code = os.getenv("ACCESS_CODE", "")
    if not expected_code or access_code != expected_code:
        return {"ok": False, "error": "Codigo de acesso invalido."}

    conn = get_connection()
    cur = get_cursor(conn)
    try:
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        cur.execute(
            """INSERT INTO users (email, password_hash, full_name, verified)
               VALUES (%s, %s, %s, true)
               RETURNING id, email, full_name, role, verified, created_at""",
            (email, password_hash, full_name),
        )
        user = dict(cur.fetchone())
        user["id"] = str(user["id"])
        conn.commit()
        return {"ok": True, "user": user}
    except Exception as e:
        conn.rollback()
        if "unique" in str(e).lower():
            return {"ok": False, "error": "Email ja cadastrado."}
        return {"ok": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


def signup_admin(email: str, password: str, full_name: str, admin_code: str) -> dict:
    expected_code = os.getenv("ADMIN_ACCESS_CODE", "")
    if not expected_code or admin_code != expected_code:
        return {"ok": False, "error": "Codigo de acesso de administrador invalido."}

    conn = get_connection()
    cur = get_cursor(conn)
    try:
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        cur.execute(
            """INSERT INTO users (email, password_hash, full_name, role, verified)
               VALUES (%s, %s, %s, 'admin', true)
               RETURNING id, email, full_name, role, verified, created_at""",
            (email, password_hash, full_name),
        )
        user = dict(cur.fetchone())
        user["id"] = str(user["id"])
        conn.commit()
        return {"ok": True, "user": user}
    except Exception as e:
        conn.rollback()
        if "unique" in str(e).lower():
            return {"ok": False, "error": "Email ja cadastrado."}
        return {"ok": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


def login(email: str, password: str) -> dict | None:
    conn = get_connection()
    cur = get_cursor(conn)
    try:
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        row = cur.fetchone()
        if row is None:
            return None
        if not bcrypt.checkpw(password.encode(), row["password_hash"].encode()):
            return None
        cur.execute(
            "UPDATE users SET last_login = %s WHERE id = %s",
            (datetime.utcnow(), row["id"]),
        )
        conn.commit()
        user = dict(row)
        user["id"] = str(user["id"])
        del user["password_hash"]
        user.pop("verification_token", None)
        user.pop("verification_sent_at", None)
        return user
    finally:
        cur.close()
        conn.close()


# ── User management ──────────────────────────────────────────────────────────

def get_user_by_id(user_id: str) -> dict | None:
    conn = get_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            "SELECT id, email, full_name, role, verified, created_at, last_login FROM users WHERE id = %s::uuid",
            (user_id,),
        )
        row = cur.fetchone()
        if row:
            row = dict(row)
            row["id"] = str(row["id"])
        return row
    finally:
        cur.close()
        conn.close()


def promote_to_admin(user_id: str) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE users SET role = 'admin' WHERE id = %s::uuid", (user_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        cur.close()
        conn.close()


def demote_from_admin(user_id: str) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE users SET role = 'user' WHERE id = %s::uuid", (user_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        cur.close()
        conn.close()


def delete_user(user_id: str) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM chat_logs WHERE user_id = %s::uuid", (user_id,))
        cur.execute("DELETE FROM sessions WHERE user_id = %s::uuid", (user_id,))
        cur.execute("DELETE FROM documents WHERE uploaded_by = %s::uuid", (user_id,))
        cur.execute("DELETE FROM users WHERE id = %s::uuid", (user_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        cur.close()
        conn.close()


def list_all_users(search: str = None) -> list[dict]:
    conn = get_connection()
    cur = get_cursor(conn)
    try:
        if search:
            cur.execute(
                """SELECT id, email, full_name, role, verified, created_at, last_login
                   FROM users
                   WHERE email ILIKE %s OR full_name ILIKE %s
                   ORDER BY created_at""",
                (f"%{search}%", f"%{search}%"),
            )
        else:
            cur.execute(
                "SELECT id, email, full_name, role, verified, created_at, last_login FROM users ORDER BY created_at"
            )
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            r["id"] = str(r["id"])
        return rows
    finally:
        cur.close()
        conn.close()


def manually_verify_user(user_id: str) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE users SET verified = true, verification_token = NULL WHERE id = %s::uuid",
            (user_id,),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        cur.close()
        conn.close()


# ── Chat logging ─────────────────────────────────────────────────────────────

def log_chat_message(user_id: str, session_id: str, role: str, message: str, sim_step: str = None):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """INSERT INTO chat_logs (user_id, session_id, role, message, sim_step)
               VALUES (%s::uuid, %s::uuid, %s, %s, %s)""",
            (user_id, session_id, role, message, sim_step),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def get_chat_logs(start_date=None, end_date=None, user_id=None) -> list[dict]:
    conn = get_connection()
    cur = get_cursor(conn)
    try:
        query = """
            SELECT cl.id, cl.user_id, u.email, u.full_name, cl.session_id,
                   cl.role, cl.message, cl.sim_step, cl.created_at
            FROM chat_logs cl
            JOIN users u ON cl.user_id = u.id
            WHERE 1=1
        """
        params = []
        if start_date:
            query += " AND cl.created_at >= %s"
            params.append(start_date)
        if end_date:
            query += " AND cl.created_at < %s"
            params.append(end_date)
        if user_id:
            query += " AND cl.user_id = %s::uuid"
            params.append(user_id)
        query += " ORDER BY cl.created_at"
        cur.execute(query, params)
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            r["id"] = str(r["id"])
            r["user_id"] = str(r["user_id"])
            r["session_id"] = str(r["session_id"])
        return rows
    finally:
        cur.close()
        conn.close()


# ── Sessions ─────────────────────────────────────────────────────────────────

def create_session(session_id: str, user_id: str):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """INSERT INTO sessions (id, user_id)
               VALUES (%s::uuid, %s::uuid)
               ON CONFLICT (id) DO NOTHING""",
            (session_id, user_id),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def update_session(session_id: str, sim_type: str = None, sim_step: str = None):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """UPDATE sessions
               SET last_message_at = now(),
                   message_count = message_count + 1,
                   sim_type = COALESCE(%s, sim_type),
                   final_sim_step = COALESCE(%s, final_sim_step)
               WHERE id = %s::uuid""",
            (sim_type, sim_step, session_id),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def get_session_summary(session_id: str) -> dict | None:
    conn = get_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            """SELECT s.*, u.email, u.full_name
               FROM sessions s
               JOIN users u ON s.user_id = u.id
               WHERE s.id = %s::uuid""",
            (session_id,),
        )
        row = cur.fetchone()
        if row:
            row = dict(row)
            row["id"] = str(row["id"])
            row["user_id"] = str(row["user_id"])
        return row
    finally:
        cur.close()
        conn.close()


def list_sessions(user_id=None, start_date=None, end_date=None,
                  sim_type=None, flagged_only=False) -> list[dict]:
    conn = get_connection()
    cur = get_cursor(conn)
    try:
        query = """
            SELECT s.id, s.user_id, u.email, u.full_name,
                   s.started_at, s.last_message_at, s.message_count,
                   s.sim_type, s.final_sim_step, s.flagged, s.flag_note
            FROM sessions s
            JOIN users u ON s.user_id = u.id
            WHERE 1=1
        """
        params = []
        if user_id:
            query += " AND s.user_id = %s::uuid"
            params.append(user_id)
        if start_date:
            query += " AND s.started_at >= %s"
            params.append(start_date)
        if end_date:
            query += " AND s.started_at < %s"
            params.append(end_date)
        if sim_type:
            if sim_type == "Conversa livre":
                query += " AND s.sim_type IS NULL"
            else:
                query += " AND s.sim_type = %s"
                params.append(sim_type)
        if flagged_only:
            query += " AND s.flagged = true"
        query += " ORDER BY s.started_at DESC"
        cur.execute(query, params)
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            r["id"] = str(r["id"])
            r["user_id"] = str(r["user_id"])
        return rows
    finally:
        cur.close()
        conn.close()


def flag_session(session_id: str, note: str):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE sessions SET flagged = true, flag_note = %s WHERE id = %s::uuid",
            (note, session_id),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def unflag_session(session_id: str):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE sessions SET flagged = false, flag_note = NULL WHERE id = %s::uuid",
            (session_id,),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def save_paused_state(session_id: str, sim_step: str, sim_data: dict):
    """Persist simulation state as JSONB so user can resume later."""
    payload = {"sim_step": sim_step, "sim_data": sim_data}
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE sessions SET paused_state = %s::jsonb WHERE id = %s::uuid",
            (json.dumps(payload), session_id),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def load_paused_state(user_id: str) -> dict | None:
    """Return the most recent paused simulation for this user, or None."""
    conn = get_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            """SELECT id, paused_state
               FROM sessions
               WHERE user_id = %s::uuid AND paused_state IS NOT NULL
               ORDER BY last_message_at DESC
               LIMIT 1""",
            (user_id,),
        )
        row = cur.fetchone()
        if row and row["paused_state"]:
            ps = row["paused_state"]
            if isinstance(ps, str):
                ps = json.loads(ps)
            ps["session_id"] = str(row["id"])
            return ps
        return None
    finally:
        cur.close()
        conn.close()


def clear_paused_state(session_id: str):
    """Remove paused state after resuming or discarding."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE sessions SET paused_state = NULL WHERE id = %s::uuid",
            (session_id,),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


# ── Dashboard stats ──────────────────────────────────────────────────────────

def get_dashboard_stats() -> dict:
    conn = get_connection()
    cur = get_cursor(conn)
    try:
        cur.execute("SELECT COUNT(*) as total FROM users")
        total_users = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(*) as cnt FROM users WHERE created_at >= now() - interval '7 days'")
        new_users_week = cur.fetchone()["cnt"]

        cur.execute("SELECT COUNT(*) as cnt FROM users WHERE verified = true")
        verified = cur.fetchone()["cnt"]

        cur.execute("SELECT COUNT(*) as cnt FROM users WHERE verified = false")
        pending = cur.fetchone()["cnt"]

        cur.execute("SELECT COUNT(*) as cnt FROM chat_logs WHERE created_at >= CURRENT_DATE")
        msgs_today = cur.fetchone()["cnt"]

        cur.execute("SELECT COUNT(*) as cnt FROM chat_logs WHERE created_at >= now() - interval '7 days'")
        msgs_week = cur.fetchone()["cnt"]

        return {
            "total_users": total_users,
            "new_users_week": new_users_week,
            "verified": verified,
            "pending": pending,
            "msgs_today": msgs_today,
            "msgs_week": msgs_week,
        }
    finally:
        cur.close()
        conn.close()


def get_daily_message_counts(days: int = 14) -> list[dict]:
    conn = get_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            """SELECT DATE(created_at) as day, COUNT(*) as count
               FROM chat_logs
               WHERE created_at >= now() - interval '%s days'
               GROUP BY DATE(created_at)
               ORDER BY day""",
            (days,),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()
        conn.close()


def get_top_users(limit: int = 5) -> list[dict]:
    conn = get_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            """SELECT u.email, u.full_name, COUNT(cl.id) as msg_count
               FROM users u
               JOIN chat_logs cl ON cl.user_id = u.id
               GROUP BY u.id, u.email, u.full_name
               ORDER BY msg_count DESC
               LIMIT %s""",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()
        conn.close()


def get_session_type_breakdown() -> dict:
    conn = get_connection()
    cur = get_cursor(conn)
    try:
        cur.execute("SELECT COUNT(*) as cnt FROM sessions WHERE sim_type IS NOT NULL")
        simulation = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(*) as cnt FROM sessions WHERE sim_type IS NULL")
        free = cur.fetchone()["cnt"]
        return {"simulation": simulation, "free": free}
    finally:
        cur.close()
        conn.close()


# ── Documents ────────────────────────────────────────────────────────────────

def get_all_documents() -> list[dict]:
    conn = get_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            """SELECT d.id, d.filename, d.chunk_count, d.qdrant_status, d.uploaded_at,
                      u.email as uploaded_by_email
               FROM documents d
               LEFT JOIN users u ON d.uploaded_by = u.id
               ORDER BY d.uploaded_at DESC"""
        )
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            r["id"] = str(r["id"])
        return rows
    finally:
        cur.close()
        conn.close()


def insert_document(filename: str, uploaded_by: str) -> str:
    conn = get_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            """INSERT INTO documents (filename, uploaded_by)
               VALUES (%s, %s::uuid)
               RETURNING id""",
            (filename, uploaded_by),
        )
        doc_id = str(cur.fetchone()["id"])
        conn.commit()
        return doc_id
    finally:
        cur.close()
        conn.close()


def update_document_status(doc_id: str, status: str, chunk_count: int = 0):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE documents SET qdrant_status = %s, chunk_count = %s WHERE id = %s::uuid",
            (status, chunk_count, doc_id),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def delete_document_record(doc_id: str):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM documents WHERE id = %s::uuid", (doc_id,))
        conn.commit()
    finally:
        cur.close()
        conn.close()
