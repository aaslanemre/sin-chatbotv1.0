import bcrypt
from datetime import datetime
from auth.db import get_connection, get_cursor


def signup(email: str, password: str, full_name: str) -> dict:
    conn = get_connection()
    cur = get_cursor(conn)
    try:
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        cur.execute(
            """INSERT INTO users (email, password_hash, full_name)
               VALUES (%s, %s, %s)
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
        return user
    finally:
        cur.close()
        conn.close()


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


def delete_user(user_id: str) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM chat_logs WHERE user_id = %s::uuid", (user_id,))
        cur.execute("DELETE FROM documents WHERE uploaded_by = %s::uuid", (user_id,))
        cur.execute("DELETE FROM users WHERE id = %s::uuid", (user_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        cur.close()
        conn.close()


def list_all_users() -> list[dict]:
    conn = get_connection()
    cur = get_cursor(conn)
    try:
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
