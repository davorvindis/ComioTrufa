"""Tests for the database module."""

import os
import tempfile

import pytest
from comiotrufa.database import Database


@pytest.fixture
def db():
    """Create a temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    database = Database(path)
    yield database
    database.close()
    os.unlink(path)


class TestDatabase:
    def test_initialize_creates_tables(self, db):
        tables = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {t["name"] for t in tables}
        assert "events" in table_names
        assert "readings" in table_names
        assert "daily_stats" in table_names

    def test_save_reading(self, db):
        db.save_reading("food", 0.95, "/tmp/img.jpg", '{"state":"food"}')
        reading = db.get_last_reading()
        assert reading["state"] == "food"
        assert reading["confidence"] == 0.95
        assert reading["image_path"] == "/tmp/img.jpg"

    def test_get_last_state_empty(self, db):
        assert db.get_last_state() is None

    def test_save_event_and_get_last_state(self, db):
        db.save_event("food", "empty", "dog_ate", 0.9, "/tmp/img.jpg")
        assert db.get_last_state() == "empty"

    def test_get_recent_events(self, db):
        db.save_event("food", "empty", "dog_ate", 0.9, "/tmp/img1.jpg")
        db.save_event("empty", "food", "bowl_refilled", 0.85, "/tmp/img2.jpg")
        events = db.get_recent_events(limit=10)
        assert len(events) == 2
        assert events[0]["event_type"] == "bowl_refilled"  # Most recent first

    def test_mark_notified(self, db):
        event_id = db.save_event("food", "empty", "dog_ate", 0.9, "/tmp/img.jpg")
        db.mark_notified(event_id)
        row = db.conn.execute(
            "SELECT notified FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        assert row["notified"] == 1

    def test_today_stats(self, db):
        # Initially empty
        stats = db.get_today_stats()
        assert stats["meals_detected"] == 0

        # After a meal
        db.save_event("food", "empty", "dog_ate", 0.9, "/tmp/img.jpg")
        stats = db.get_today_stats()
        assert stats["meals_detected"] == 1
        assert stats["first_meal_time"] is not None

    def test_multiple_meals_increment(self, db):
        db.save_event("food", "empty", "dog_ate", 0.9, "/tmp/img1.jpg")
        db.save_event("empty", "food", "bowl_refilled", 0.9, "/tmp/img2.jpg")
        db.save_event("food", "empty", "dog_ate", 0.9, "/tmp/img3.jpg")

        stats = db.get_today_stats()
        assert stats["meals_detected"] == 2
        assert stats["refills"] == 1

    def test_get_last_eat_time(self, db):
        assert db.get_last_eat_time() is None
        db.save_event("food", "empty", "dog_ate", 0.9, "/tmp/img.jpg")
        assert db.get_last_eat_time() is not None
