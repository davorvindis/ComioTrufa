"""ComioTrufa - Main entry point.

Orchestrates camera capture, vision analysis, state machine,
database, and Telegram notifications in an async loop.
"""

import asyncio
import logging
import signal
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .camera import Camera
from .config import load_config, Config
from .database import Database
from .state_machine import BowlStateMachine, EVENT_DOG_ATE, EVENT_BOWL_REFILLED, STATE_EMPTY
from .telegram_bot import TelegramBot
from .vision import VisionAnalyzer


def setup_logging(config: Config):
    """Configure logging with file rotation."""
    log_dir = Path(config.logging.file).parent
    log_dir.mkdir(parents=True, exist_ok=True)

    handler = RotatingFileHandler(
        config.logging.file,
        maxBytes=config.logging.max_size_mb * 1024 * 1024,
        backupCount=config.logging.backup_count,
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(config.logging.level)
    root_logger.addHandler(handler)
    root_logger.addHandler(console_handler)


logger = logging.getLogger(__name__)


class ComioTrufa:
    """Main application class."""

    def __init__(self, config_path: str = "config.yaml"):
        self.config = load_config(config_path)
        setup_logging(self.config)

        self.db = Database(self.config.database.path)
        self.camera = Camera(self.config.camera)
        self.vision = VisionAnalyzer(self.config.claude)
        self.state_machine = BowlStateMachine(
            initial_state=self.db.get_last_state(),
            debounce_threshold=self.config.monitor.debounce_readings,
        )
        self.bot = TelegramBot(self.config.telegram, self.db)
        self.bot.set_capture_callback(self._on_demand_capture)

        self._running = False
        self._last_empty_notification: datetime | None = None

    async def _on_demand_capture(self) -> str:
        """Callback for Telegram /photo command."""
        return self.camera.capture()

    async def run(self):
        """Start the main monitoring loop."""
        logger.info("ComioTrufa starting...")
        logger.info(f"  Interval: {self.config.monitor.interval_minutes} min")
        logger.info(f"  Debounce: {self.config.monitor.debounce_readings} readings")
        logger.info(f"  Model: {self.config.claude.model}")
        logger.info(f"  Initial state: {self.state_machine.current_state}")

        # Validate configuration
        if not self.config.claude.api_key:
            logger.error("ANTHROPIC_API_KEY not set!")
            sys.exit(1)
        if not self.config.telegram.bot_token:
            logger.error("TELEGRAM_BOT_TOKEN not set!")
            sys.exit(1)
        if not self.config.telegram.chat_id:
            logger.error("TELEGRAM_CHAT_ID not set!")
            sys.exit(1)

        # Start Telegram bot
        await self.bot.start()
        logger.info("Telegram bot started")

        # Main loop
        self._running = True
        interval = self.config.monitor.interval_minutes * 60

        try:
            while self._running:
                await self._monitor_cycle()
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass
        finally:
            await self._shutdown()

    async def _monitor_cycle(self):
        """Execute one monitoring cycle: capture → analyze → update state."""
        try:
            # 1. Capture photo
            image_path = self.camera.capture()
            logger.debug(f"Captured: {image_path}")

            # 2. Analyze with Claude Vision
            result = self.vision.analyze(image_path)
            if result is None:
                logger.warning("Vision analysis failed, skipping cycle")
                return

            logger.info(
                f"Analysis: state={result.state}, confidence={result.confidence:.2f}, "
                f"desc='{result.description}'"
            )

            # 3. Save reading
            self.db.save_reading(
                state=result.state,
                confidence=result.confidence,
                image_path=image_path,
                raw_response=result.raw_response,
            )

            # 4. Process state machine
            event = self.state_machine.process_reading(
                result.state, result.confidence, image_path
            )

            # 5. Handle events
            if event:
                event_id = self.db.save_event(
                    previous_state=event.previous_state,
                    new_state=event.new_state,
                    event_type=event.event_type,
                    confidence=event.confidence,
                    image_path=event.image_path,
                )
                logger.info(f"State change: {event.previous_state} → {event.new_state} ({event.event_type})")

                if event.event_type == EVENT_DOG_ATE and self.config.telegram.notify_on_eat:
                    await self.bot.notify_ate(event.image_path, event.confidence)
                    self.db.mark_notified(event_id)
                    self._last_empty_notification = None

                elif event.event_type == EVENT_BOWL_REFILLED and self.config.telegram.notify_on_refill:
                    await self.bot.notify_refilled(event.image_path)
                    self.db.mark_notified(event_id)
                    self._last_empty_notification = None

            # 6. Check empty reminder
            await self._check_empty_reminder()

            # 7. Periodic cleanup
            self.db.cleanup_old_images(
                self.config.camera.keep_images_days,
                self.config.camera.images_dir,
            )

        except Exception as e:
            logger.error(f"Error in monitoring cycle: {e}", exc_info=True)

    async def _check_empty_reminder(self):
        """Send reminder if bowl has been empty too long."""
        reminder_hours = self.config.telegram.empty_reminder_hours
        if reminder_hours <= 0:
            return

        if self.state_machine.current_state != STATE_EMPTY:
            self._last_empty_notification = None
            return

        last_eat = self.db.get_last_eat_time()
        if not last_eat:
            return

        last_eat_dt = datetime.fromisoformat(last_eat)
        hours_empty = (datetime.now() - last_eat_dt).total_seconds() / 3600

        if hours_empty >= reminder_hours:
            # Only notify once per reminder period
            if self._last_empty_notification:
                since_last = (datetime.now() - self._last_empty_notification).total_seconds() / 3600
                if since_last < reminder_hours:
                    return

            await self.bot.notify_empty_reminder(hours_empty)
            self._last_empty_notification = datetime.now()

    async def _shutdown(self):
        """Clean shutdown."""
        logger.info("Shutting down...")
        await self.bot.stop()
        self.camera.close()
        self.db.close()
        logger.info("ComioTrufa stopped.")

    def stop(self):
        """Signal the main loop to stop."""
        self._running = False


def main():
    """Entry point for the application."""
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    app = ComioTrufa(config_path)

    loop = asyncio.new_event_loop()

    # Handle graceful shutdown
    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}, stopping...")
        app.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        loop.run_until_complete(app.run())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
