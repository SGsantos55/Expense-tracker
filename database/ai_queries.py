"""Persistence helpers for cached AI summaries, chat history and usage."""
import secrets

from psycopg.types.json import Jsonb

from database.db import get_db


def get_cached_summary(user_id, period_start, period_end, prompt_version, model, fingerprint):
    conn = get_db()
    try:
        row = conn.execute(
            """
            SELECT id, summary, facts, data_fingerprint, prompt_version, model, generated_at
            FROM ai_summaries
            WHERE user_id = %s
              AND period_start = %s
              AND period_end = %s
              AND prompt_version = %s
              AND model = %s
              AND data_fingerprint = %s
            """,
            (user_id, period_start, period_end, prompt_version, model, fingerprint),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def save_summary(
    user_id,
    period_preset,
    period_start,
    period_end,
    facts,
    summary,
    fingerprint,
    prompt_version,
    model,
):
    conn = get_db()
    try:
        row = conn.execute(
            """
            INSERT INTO ai_summaries (
                user_id, period_preset, period_start, period_end, facts, summary,
                data_fingerprint, prompt_version, model
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id, period_start, period_end, prompt_version, model)
            DO UPDATE SET
                period_preset = EXCLUDED.period_preset,
                facts = EXCLUDED.facts,
                summary = EXCLUDED.summary,
                data_fingerprint = EXCLUDED.data_fingerprint,
                generated_at = now()::text
            RETURNING generated_at
            """,
            (
                user_id,
                period_preset,
                period_start,
                period_end,
                Jsonb(facts),
                Jsonb(summary),
                fingerprint,
                prompt_version,
                model,
            ),
        ).fetchone()
        conn.commit()
        return row["generated_at"]
    finally:
        conn.close()


def count_recent_usage(user_id, kind, minutes=60):
    conn = get_db()
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM ai_usage
            WHERE user_id = %s
              AND kind = %s
              AND created_at::timestamp >= now() - (%s * interval '1 minute')
            """,
            (user_id, kind, minutes),
        ).fetchone()
        return int(row["count"])
    finally:
        conn.close()


def record_usage(user_id, kind, model, input_tokens=0, output_tokens=0, latency_ms=0):
    conn = get_db()
    try:
        conn.execute(
            """
            INSERT INTO ai_usage (
                user_id, kind, model, input_tokens, output_tokens, latency_ms
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                user_id,
                kind,
                model,
                int(input_tokens or 0),
                int(output_tokens or 0),
                int(latency_ms or 0),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_fingerprint_stats(user_id):
    conn = get_db()
    try:
        row = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM expenses WHERE user_id = %s) AS expense_count,
                (SELECT COALESCE(SUM(amount), 0)::text FROM expenses WHERE user_id = %s) AS expense_total,
                (
                    SELECT COALESCE(string_agg(
                        id::text || ':' || date || ':' || amount::text || ':' ||
                        COALESCE(category, '') || ':' || COALESCE(description, ''),
                        '|' ORDER BY id
                    ), '')
                    FROM expenses WHERE user_id = %s
                ) AS expenses,
                (SELECT COUNT(*) FROM income_entries WHERE user_id = %s) AS income_count,
                (SELECT COALESCE(SUM(amount), 0)::text FROM income_entries WHERE user_id = %s) AS income_total,
                (
                    SELECT COALESCE(string_agg(
                        id::text || ':' || effective_month || ':' || amount::text || ':' ||
                        COALESCE(source, ''),
                        '|' ORDER BY id
                    ), '')
                    FROM income_entries WHERE user_id = %s
                ) AS income
            """,
            (user_id, user_id, user_id, user_id, user_id, user_id),
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def create_chat_session(user_id, period_start=None, period_end=None):
    session_id = secrets.token_urlsafe(24)
    conn = get_db()
    try:
        conn.execute(
            """
            INSERT INTO ai_chat_sessions (id, user_id, period_start, period_end)
            VALUES (%s, %s, %s, %s)
            """,
            (session_id, user_id, period_start, period_end),
        )
        conn.commit()
        return session_id
    finally:
        conn.close()


def chat_session_exists(session_id, user_id):
    if not session_id:
        return False
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT 1 FROM ai_chat_sessions WHERE id = %s AND user_id = %s",
            (session_id, user_id),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def get_chat_history(session_id, user_id, limit=20):
    if not session_id:
        return []
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT role, content, created_at
            FROM ai_chat_messages
            WHERE session_id = %s AND user_id = %s
            ORDER BY id DESC
            LIMIT %s
            """,
            (session_id, user_id, int(limit)),
        ).fetchall()
        return [dict(row) for row in reversed(rows)]
    finally:
        conn.close()


def append_chat_messages(session_id, user_id, messages):
    if not messages:
        return
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO ai_chat_messages (session_id, user_id, role, content)
                VALUES (%s, %s, %s, %s)
                """,
                [
                    (session_id, user_id, message["role"], message["content"])
                    for message in messages
                ],
            )
            cur.execute(
                "UPDATE ai_chat_sessions SET updated_at = now()::text "
                "WHERE id = %s AND user_id = %s",
                (session_id, user_id),
            )
        conn.commit()
    finally:
        conn.close()


def delete_chat_session(session_id, user_id):
    if not session_id:
        return False
    conn = get_db()
    try:
        conn.execute(
            "DELETE FROM ai_chat_messages WHERE session_id = %s AND user_id = %s",
            (session_id, user_id),
        )
        cursor = conn.execute(
            "DELETE FROM ai_chat_sessions WHERE id = %s AND user_id = %s",
            (session_id, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()
