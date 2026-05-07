"""SQLite database module for ComioTrufa."""

import base64
import sqlite3
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._connect()
        self.initialize()

    def _connect(self):
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")

    def initialize(self):
        """Create tables if they don't exist."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                previous_state TEXT NOT NULL,
                new_state TEXT NOT NULL,
                event_type TEXT NOT NULL,
                confidence REAL,
                image_path TEXT,
                notified INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                state TEXT NOT NULL,
                confidence REAL,
                image_path TEXT,
                image_data TEXT,
                raw_response TEXT
            );

            CREATE TABLE IF NOT EXISTS daily_stats (
                date TEXT PRIMARY KEY,
                meals_detected INTEGER DEFAULT 0,
                first_meal_time TEXT,
                last_meal_time TEXT,
                refills INTEGER DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
            CREATE INDEX IF NOT EXISTS idx_readings_timestamp ON readings(timestamp);
        """)
        # Add image_data column if it doesn't exist (migration)
        try:
            self.conn.execute("SELECT image_data FROM readings LIMIT 1")
        except sqlite3.OperationalError:
            self.conn.execute("ALTER TABLE readings ADD COLUMN image_data TEXT")
        self.conn.commit()

    def save_reading(self, state: str, confidence: float, image_path: str,
                     raw_response: str = "", image_data: str = ""):
        """Save a raw reading from the vision analysis."""
        self.conn.execute(
            "INSERT INTO readings (state, confidence, image_path, image_data, raw_response) "
            "VALUES (?, ?, ?, ?, ?)",
            (state, confidence, image_path, image_data, raw_response),
        )
        self.conn.commit()

    def save_event(self, previous_state: str, new_state: str, event_type: str,
                   confidence: float, image_path: str) -> int:
        """Save a state transition event. Returns the event ID."""
        cursor = self.conn.execute(
            "INSERT INTO events (previous_state, new_state, event_type, confidence, image_path) "
            "VALUES (?, ?, ?, ?, ?)",
            (previous_state, new_state, event_type, confidence, image_path),
        )
        self.conn.commit()

        if event_type == "dog_ate":
            self._update_daily_stats_meal()
        elif event_type == "bowl_refilled":
            self._update_daily_stats_refill()

        return cursor.lastrowid

    def mark_notified(self, event_id: int):
        self.conn.execute("UPDATE events SET notified = 1 WHERE id = ?", (event_id,))
        self.conn.commit()

    def get_last_state(self) -> Optional[str]:
        row = self.conn.execute(
            "SELECT new_state FROM events ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        return row["new_state"] if row else None

    def get_last_reading(self) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT id, timestamp, state, confidence, image_path, raw_response FROM readings "
            "ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def get_readings_by_date(self, target_date: str, limit: int = 100) -> list[dict]:
        """Get readings for a specific date (YYYY-MM-DD)."""
        rows = self.conn.execute(
            "SELECT id, timestamp, state, confidence, image_path, raw_response "
            "FROM readings WHERE date(timestamp) = ? ORDER BY timestamp DESC LIMIT ?",
            (target_date, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_reading_image(self, reading_id: int) -> Optional[str]:
        """Get base64 image data for a specific reading."""
        row = self.conn.execute(
            "SELECT image_data FROM readings WHERE id = ?", (reading_id,)
        ).fetchone()
        return row["image_data"] if row and row["image_data"] else None

    def get_recent_events(self, limit: int = 10) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM events WHERE event_type IN ('dog_ate', 'bowl_refilled') "
            "ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_events_by_date(self, target_date: str) -> list[dict]:
        """Get events for a specific date."""
        rows = self.conn.execute(
            "SELECT * FROM events WHERE event_type IN ('dog_ate', 'bowl_refilled') "
            "AND date(timestamp) = ? ORDER BY timestamp DESC",
            (target_date,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_today_stats(self) -> dict:
        today = date.today().isoformat()
        return self.get_date_stats(today)

    def get_date_stats(self, target_date: str) -> dict:
        row = self.conn.execute(
            "SELECT * FROM daily_stats WHERE date = ?", (target_date,)
        ).fetchone()
        if row:
            return dict(row)
        return {"date": target_date, "meals_detected": 0, "first_meal_time": None,
                "last_meal_time": None, "refills": 0}

    def get_week_stats(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM daily_stats ORDER BY date DESC LIMIT 7"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_dates_with_data(self) -> list[str]:
        """Get all dates that have readings."""
        rows = self.conn.execute(
            "SELECT DISTINCT date(timestamp) as d FROM readings ORDER BY d DESC"
        ).fetchall()
        return [r["d"] for r in rows]

    def get_last_eat_time(self) -> Optional[str]:
        row = self.conn.execute(
            "SELECT timestamp FROM events WHERE event_type = 'dog_ate' "
            "ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        return row["timestamp"] if row else None

    def _update_daily_stats_meal(self):
        today = date.today().isoformat()
        now = datetime.now().strftime("%H:%M:%S")
        self.conn.execute("""
            INSERT INTO daily_stats (date, meals_detected, first_meal_time, last_meal_time)
            VALUES (?, 1, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                meals_detected = meals_detected + 1,
                first_meal_time = COALESCE(first_meal_time, ?),
                last_meal_time = ?
        """, (today, now, now, now, now))
        self.conn.commit()

    def _update_daily_stats_refill(self):
        today = date.today().isoformat()
        self.conn.execute("""
            INSERT INTO daily_stats (date, refills)
            VALUES (?, 1)
            ON CONFLICT(date) DO UPDATE SET refills = refills + 1
        """, (today,))
        self.conn.commit()

    def cleanup_old_readings(self, keep_days: int):
        """Delete old readings (but keep image_data in DB)."""
        cutoff = (datetime.now() - timedelta(days=keep_days)).isoformat()
        # Delete filesystem images
        rows = self.conn.execute(
            "SELECT image_path FROM readings WHERE timestamp < ? AND image_path IS NOT NULL",
            (cutoff,),
        ).fetchall()
        for row in rows:
            path = Path(row["image_path"])
            if path.exists():
                path.unlink()
        # Remove old readings from DB
        self.conn.execute("DELETE FROM readings WHERE timestamp < ?", (cutoff,))
        self.conn.commit()

    def close(self):
        self.conn.close()
