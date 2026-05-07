"""ComioTrufa Server - Receives photos from ESP32-CAM and processes them.

Run with: uvicorn server.app:app --host 0.0.0.0 --port 8000
"""

import asyncio
import base64
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

# Forzar timezone Argentina
os.environ["TZ"] = "America/Argentina/Buenos_Aires"
try:
    import time
    time.tzset()
except AttributeError:
    pass  # Windows no tiene tzset

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from comiotrufa.config import load_config
from comiotrufa.database import Database
from comiotrufa.state_machine import (
    BowlStateMachine,
    EVENT_DOG_ATE,
    EVENT_BOWL_REFILLED,
    STATE_EMPTY,
)
from comiotrufa.telegram_bot import TelegramBot
from comiotrufa.vision import VisionAnalyzer

logger = logging.getLogger(__name__)

# Global state
config = None
db = None
state_machine = None
vision = None
bot = None
reminder_task = None
photo_requested = False  # Flag for on-demand photo requests


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    global config, db, state_machine, vision, bot, reminder_task

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Load config
    config_path = Path(__file__).parent.parent / "config.yaml"
    config = load_config(str(config_path))

    # Initialize components
    Path(config.camera.images_dir).mkdir(parents=True, exist_ok=True)
    db = Database(config.database.path)
    state_machine = BowlStateMachine(
        initial_state=db.get_last_state(),
        debounce_threshold=config.monitor.debounce_readings,
    )
    vision = VisionAnalyzer(config.claude)
    bot = TelegramBot(config.telegram, db)

    # Start Telegram bot
    await bot.start()
    logger.info("ComioTrufa Server started")
    logger.info(f"  State: {state_machine.current_state}")
    logger.info(f"  Debounce: {config.monitor.debounce_readings} readings")

    # Start empty bowl reminder checker
    reminder_task = asyncio.create_task(empty_reminder_loop())

    yield

    # Shutdown
    reminder_task.cancel()
    await bot.stop()
    db.close()
    logger.info("ComioTrufa Server stopped")


app = FastAPI(title="ComioTrufa", lifespan=lifespan)


# ─── ESP32-CAM Endpoint ──────────────────────────────────────

@app.post("/api/photo")
async def receive_photo(request: Request):
    """Receive a JPEG photo from ESP32-CAM and process it."""
    body = await request.body()

    if len(body) == 0:
        return Response(content="Empty body", status_code=400)

    if len(body) < 1000:
        return Response(content="Image too small", status_code=400)

    logger.info(f"Received photo: {len(body)} bytes")

    # Save image to disk
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"bowl_{timestamp}.jpg"
    filepath = Path(config.camera.images_dir) / filename
    filepath.write_bytes(body)

    # Analyze with Vision API
    result = vision.analyze(str(filepath))
    if result is None:
        logger.warning("Vision analysis failed")
        return Response(content='{"status":"error","detail":"vision_failed"}', status_code=500)

    logger.info(f"Analysis: state={result.state}, confidence={result.confidence:.2f}")

    # Save reading with base64 image data for persistence
    image_b64 = base64.b64encode(body).decode("utf-8")
    db.save_reading(
        state=result.state,
        confidence=result.confidence,
        image_path=str(filepath),
        raw_response=result.raw_response,
        image_data=image_b64,
    )

    # Process state machine
    event = state_machine.process_reading(result.state, result.confidence, str(filepath))

    response_data = {
        "status": "ok",
        "state": result.state,
        "confidence": result.confidence,
    }

    if event:
        event_id = db.save_event(
            previous_state=event.previous_state,
            new_state=event.new_state,
            event_type=event.event_type,
            confidence=event.confidence,
            image_path=event.image_path,
        )
        logger.info(f"State change: {event.previous_state} -> {event.new_state} ({event.event_type})")
        response_data["event"] = event.event_type

        # Send notifications
        if event.event_type == EVENT_DOG_ATE and config.telegram.notify_on_eat:
            await bot.notify_ate(event.image_path, event.confidence)
            db.mark_notified(event_id)
        elif event.event_type == EVENT_BOWL_REFILLED and config.telegram.notify_on_refill:
            await bot.notify_refilled(event.image_path)
            db.mark_notified(event_id)

    # Periodic cleanup
    db.cleanup_old_readings(config.camera.keep_images_days)

    return Response(content=json.dumps(response_data), media_type="application/json")


# ─── API Endpoints for Frontend ──────────────────────────────

@app.post("/api/request-photo")
async def request_photo():
    """Request the ESP32 to send a photo on its next check-in."""
    global photo_requested
    photo_requested = True
    return Response(content='{"status":"requested"}', media_type="application/json")


@app.get("/api/should-capture")
async def should_capture():
    """ESP32 polls this to know if it should send a photo immediately."""
    global photo_requested
    should = photo_requested
    if photo_requested:
        photo_requested = False
    return Response(
        content=json.dumps({"capture": should}),
        media_type="application/json",
    )


@app.get("/api/status")
async def get_status():
    """Get current bowl status."""
    reading = db.get_last_reading()
    last_eat = db.get_last_eat_time()
    return Response(
        content=json.dumps({
            "current_state": state_machine.current_state,
            "last_reading": reading,
            "last_eat_time": last_eat,
        }),
        media_type="application/json",
    )


@app.get("/api/readings")
async def get_readings(limit: int = 50, date: str = ""):
    """Get readings, optionally filtered by date."""
    if date:
        readings = db.get_readings_by_date(date, limit=limit)
    else:
        rows = db.conn.execute(
            "SELECT id, timestamp, state, confidence, image_path, raw_response "
            "FROM readings ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        readings = [dict(r) for r in rows]
    for r in readings:
        r["image_url"] = f"/api/image/{r['id']}"
    return Response(content=json.dumps(readings), media_type="application/json")


@app.get("/api/events")
async def get_events(limit: int = 50, date: str = ""):
    """Get events, optionally filtered by date."""
    if date:
        events = db.get_events_by_date(date)
    else:
        events = db.get_recent_events(limit=limit)
    return Response(content=json.dumps(events), media_type="application/json")


@app.get("/api/today")
async def get_today():
    stats = db.get_today_stats()
    return Response(content=json.dumps(stats), media_type="application/json")


@app.get("/api/stats/{date}")
async def get_date_stats(date: str):
    stats = db.get_date_stats(date)
    return Response(content=json.dumps(stats), media_type="application/json")


@app.get("/api/week")
async def get_week():
    stats = db.get_week_stats()
    return Response(content=json.dumps(stats), media_type="application/json")


@app.get("/api/dates")
async def get_dates():
    """Get list of dates with data."""
    dates = db.get_dates_with_data()
    return Response(content=json.dumps(dates), media_type="application/json")


@app.get("/api/image/{reading_id}")
async def serve_image_from_db(reading_id: int):
    """Serve image from database (base64) or filesystem fallback."""
    # Try DB first (persists on Render)
    image_b64 = db.get_reading_image(reading_id)
    if image_b64:
        image_bytes = base64.b64decode(image_b64)
        return Response(content=image_bytes, media_type="image/jpeg")

    # Fallback to filesystem
    row = db.conn.execute(
        "SELECT image_path FROM readings WHERE id = ?", (reading_id,)
    ).fetchone()
    if row and row["image_path"]:
        filepath = Path(row["image_path"])
        if filepath.exists():
            return FileResponse(filepath, media_type="image/jpeg")

    return Response(content="Not found", status_code=404)


@app.get("/images/{filename}")
async def serve_image_file(filename: str):
    """Serve captured images from filesystem (legacy)."""
    filepath = Path(config.camera.images_dir) / filename
    if not filepath.exists():
        return Response(content="Not found", status_code=404)
    return FileResponse(filepath, media_type="image/jpeg")


# ─── Frontend ────────────────────────────────────────────────

@app.get("/")
async def index():
    """Serve the frontend."""
    html_path = Path(__file__).parent / "index.html"
    return HTMLResponse(html_path.read_text())


# ─── Admin Endpoints ─────────────────────────────────────────

@app.delete("/api/reading/{reading_id}")
async def delete_reading(reading_id: int):
    """Delete a reading (photo)."""
    db.conn.execute("DELETE FROM readings WHERE id = ?", (reading_id,))
    db.conn.commit()
    return Response(content='{"status":"deleted"}', media_type="application/json")


@app.post("/api/admin/fix-stats")
async def fix_stats(request: Request):
    """Manually set daily stats. Body: {"date":"2026-05-07","meals":2,"last_eat":"09:30:00"}"""
    data = json.loads(await request.body())
    target_date = data.get("date")
    meals = data.get("meals", 0)
    first_meal = data.get("first_meal", None)
    last_meal = data.get("last_meal", None)
    refills = data.get("refills", 0)
    db.conn.execute("""
        INSERT INTO daily_stats (date, meals_detected, first_meal_time, last_meal_time, refills)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(date) DO UPDATE SET
            meals_detected = ?, first_meal_time = ?, last_meal_time = ?, refills = ?
    """, (target_date, meals, first_meal, last_meal, refills,
          meals, first_meal, last_meal, refills))
    db.conn.commit()
    return Response(content='{"status":"updated"}', media_type="application/json")


@app.post("/api/admin/reset-state")
async def reset_state():
    """Reset the state machine to unknown."""
    state_machine.current_state = "unknown"
    state_machine._pending_state = None
    state_machine._pending_count = 0
    return Response(content='{"status":"reset"}', media_type="application/json")


@app.get("/health")
async def health():
    """Health check endpoint."""
    return Response(content='{"status":"healthy"}', media_type="application/json")


async def empty_reminder_loop():
    """Background task: remind if bowl empty for too long."""
    while True:
        await asyncio.sleep(30 * 60)  # Check every 30 minutes
        try:
            reminder_hours = config.telegram.empty_reminder_hours
            if reminder_hours <= 0:
                continue
            if state_machine.current_state != STATE_EMPTY:
                continue

            last_eat = db.get_last_eat_time()
            if not last_eat:
                continue

            last_eat_dt = datetime.fromisoformat(last_eat)
            hours_empty = (datetime.now() - last_eat_dt).total_seconds() / 3600

            if hours_empty >= reminder_hours:
                await bot.notify_empty_reminder(hours_empty)
        except Exception as e:
            logger.error(f"Reminder loop error: {e}")
