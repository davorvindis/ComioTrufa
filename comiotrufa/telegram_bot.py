"""Telegram bot for ComioTrufa.

Handles commands and sends notifications when the dog eats.
"""

import logging
from datetime import datetime
from typing import Optional

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from .config import TelegramConfig
from .database import Database
from .state_machine import STATE_FOOD, STATE_EMPTY

logger = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self, config: TelegramConfig, db: Database):
        self.config = config
        self.db = db
        self.app: Optional[Application] = None
        self._capture_callback = None

    def set_capture_callback(self, callback):
        """Set callback function for on-demand photo capture.

        The callback should be an async function that returns the image path.
        """
        self._capture_callback = callback

    async def start(self):
        """Initialize and start the Telegram bot."""
        self.app = (
            Application.builder()
            .token(self.config.bot_token)
            .build()
        )

        # Register command handlers
        self.app.add_handler(CommandHandler("start", self._cmd_start))
        self.app.add_handler(CommandHandler("status", self._cmd_status))
        self.app.add_handler(CommandHandler("photo", self._cmd_photo))
        self.app.add_handler(CommandHandler("history", self._cmd_history))
        self.app.add_handler(CommandHandler("today", self._cmd_today))
        self.app.add_handler(CommandHandler("week", self._cmd_week))
        self.app.add_handler(CommandHandler("help", self._cmd_help))

        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()
        logger.info("Telegram bot started")

    async def stop(self):
        """Stop the Telegram bot."""
        if self.app:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()

    async def notify_ate(self, image_path: str, confidence: float):
        """Send notification that the dog ate."""
        text = (
            "🐕 ¡Tu perrita comió!\n"
            f"📅 {datetime.now().strftime('%H:%M del %d/%m/%Y')}\n"
            f"📊 Confianza: {confidence:.0%}"
        )
        await self._send_photo_message(text, image_path)

    async def notify_refilled(self, image_path: str):
        """Send notification that the bowl was refilled."""
        text = (
            "🍽️ Plato rellenado\n"
            f"📅 {datetime.now().strftime('%H:%M del %d/%m/%Y')}"
        )
        await self._send_photo_message(text, image_path)

    async def notify_empty_reminder(self, hours_empty: float):
        """Send reminder that bowl has been empty for a while."""
        text = (
            f"⚠️ El plato lleva vacío {hours_empty:.1f} horas.\n"
            "¿Ya le pusiste comida?"
        )
        await self._send_message(text)

    async def _send_message(self, text: str):
        """Send a text message to the configured chat."""
        try:
            await self.app.bot.send_message(
                chat_id=self.config.chat_id,
                text=text,
            )
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")

    async def _send_photo_message(self, caption: str, image_path: str):
        """Send a photo with caption to the configured chat."""
        try:
            with open(image_path, "rb") as photo:
                await self.app.bot.send_photo(
                    chat_id=self.config.chat_id,
                    photo=photo,
                    caption=caption,
                )
        except Exception as e:
            logger.error(f"Failed to send Telegram photo: {e}")
            # Fallback to text-only
            await self._send_message(caption)

    # ─── Command Handlers ─────────────────────────────────────────

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🐕 ¡Hola! Soy ComioTrufa.\n"
            "Te aviso cuando tu perrita come.\n\n"
            "Usa /help para ver los comandos disponibles."
        )

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show current bowl state."""
        reading = self.db.get_last_reading()
        last_eat = self.db.get_last_eat_time()

        if not reading:
            await update.message.reply_text("Sin datos aún. Esperando primera lectura...")
            return

        state_emoji = "🍽️ Con comida" if reading["state"] == STATE_FOOD else "⭕ Vacío"
        text = f"📊 **Estado actual**: {state_emoji}\n"
        text += f"🕐 Última lectura: {reading['timestamp']}\n"
        text += f"📈 Confianza: {reading['confidence']:.0%}\n"

        if last_eat:
            text += f"🐕 Última comida: {last_eat}"

        await update.message.reply_text(text)

    async def _cmd_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Take and send a photo right now."""
        if not self._capture_callback:
            await update.message.reply_text("Cámara no disponible.")
            return

        await update.message.reply_text("📸 Tomando foto...")
        try:
            image_path = await self._capture_callback()
            with open(image_path, "rb") as photo:
                await update.message.reply_photo(photo=photo, caption="📸 Foto actual del plato")
        except Exception as e:
            await update.message.reply_text(f"Error al tomar foto: {e}")

    async def _cmd_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show last 10 events."""
        events = self.db.get_recent_events(limit=10)
        if not events:
            await update.message.reply_text("Sin eventos registrados aún.")
            return

        lines = ["📋 **Últimos eventos:**\n"]
        for ev in events:
            emoji = "🐕" if ev["event_type"] == "dog_ate" else "🍽️"
            action = "Comió" if ev["event_type"] == "dog_ate" else "Rellenado"
            lines.append(f"{emoji} {action} - {ev['timestamp']}")

        await update.message.reply_text("\n".join(lines))

    async def _cmd_today(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show today's summary."""
        stats = self.db.get_today_stats()
        text = (
            f"📅 **Hoy ({stats['date']}):**\n"
            f"🐕 Comidas detectadas: {stats['meals_detected']}\n"
            f"🕐 Primera comida: {stats['first_meal_time'] or 'N/A'}\n"
            f"🕐 Última comida: {stats['last_meal_time'] or 'N/A'}\n"
            f"🍽️ Rellenados: {stats['refills']}"
        )
        await update.message.reply_text(text)

    async def _cmd_week(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show week summary."""
        stats = self.db.get_week_stats()
        if not stats:
            await update.message.reply_text("Sin datos de la semana aún.")
            return

        lines = ["📊 **Resumen semanal:**\n"]
        total_meals = 0
        for day in stats:
            meals = day["meals_detected"]
            total_meals += meals
            first = day["first_meal_time"] or "--:--"
            lines.append(f"  {day['date']}: {meals} comida(s), primera a las {first}")

        lines.append(f"\n📈 Total semana: {total_meals} comidas")
        if stats:
            avg = total_meals / len(stats)
            lines.append(f"📊 Promedio: {avg:.1f} comidas/día")

        await update.message.reply_text("\n".join(lines))

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🐕 **ComioTrufa - Comandos:**\n\n"
            "/status - Estado actual del plato\n"
            "/photo - Tomar foto ahora\n"
            "/history - Últimos 10 eventos\n"
            "/today - Resumen de hoy\n"
            "/week - Resumen semanal\n"
            "/help - Esta ayuda"
        )
