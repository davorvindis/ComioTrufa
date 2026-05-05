"""Configuration loader for ComioTrufa."""

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class CameraConfig:
    resolution: tuple[int, int] = (1280, 720)
    rotation: int = 0
    image_quality: int = 70
    images_dir: str = "images"
    keep_images_days: int = 7


@dataclass
class MonitorConfig:
    interval_minutes: int = 5
    debounce_readings: int = 2


@dataclass
class ClaudeConfig:
    api_key: str = ""
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 200
    timeout_seconds: int = 30


@dataclass
class TelegramConfig:
    bot_token: str = ""
    chat_id: str = ""
    notify_on_eat: bool = True
    notify_on_refill: bool = False
    empty_reminder_hours: int = 8


@dataclass
class DatabaseConfig:
    path: str = "comiotrufa.db"


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file: str = "logs/comiotrufa.log"
    max_size_mb: int = 10
    backup_count: int = 3


@dataclass
class Config:
    camera: CameraConfig = field(default_factory=CameraConfig)
    monitor: MonitorConfig = field(default_factory=MonitorConfig)
    claude: ClaudeConfig = field(default_factory=ClaudeConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    base_dir: Path = field(default_factory=lambda: Path.cwd())


def load_config(config_path: str = "config.yaml") -> Config:
    """Load configuration from YAML file and environment variables."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(path) as f:
        data = yaml.safe_load(f)

    base_dir = path.parent.resolve()

    camera_data = data.get("camera", {})
    camera = CameraConfig(
        resolution=tuple(camera_data.get("resolution", [1280, 720])),
        rotation=camera_data.get("rotation", 0),
        image_quality=camera_data.get("image_quality", 70),
        images_dir=str(base_dir / camera_data.get("images_dir", "images")),
        keep_images_days=camera_data.get("keep_images_days", 7),
    )

    monitor_data = data.get("monitor", {})
    monitor = MonitorConfig(
        interval_minutes=monitor_data.get("interval_minutes", 5),
        debounce_readings=monitor_data.get("debounce_readings", 2),
    )

    claude_data = data.get("claude", {})
    claude = ClaudeConfig(
        api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        model=claude_data.get("model", "claude-sonnet-4-20250514"),
        max_tokens=claude_data.get("max_tokens", 200),
        timeout_seconds=claude_data.get("timeout_seconds", 30),
    )

    telegram_data = data.get("telegram", {})
    telegram = TelegramConfig(
        bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
        notify_on_eat=telegram_data.get("notify_on_eat", True),
        notify_on_refill=telegram_data.get("notify_on_refill", False),
        empty_reminder_hours=telegram_data.get("empty_reminder_hours", 8),
    )

    db_data = data.get("database", {})
    database = DatabaseConfig(
        path=str(base_dir / db_data.get("path", "comiotrufa.db")),
    )

    log_data = data.get("logging", {})
    logging_config = LoggingConfig(
        level=log_data.get("level", "INFO"),
        file=str(base_dir / log_data.get("file", "logs/comiotrufa.log")),
        max_size_mb=log_data.get("max_size_mb", 10),
        backup_count=log_data.get("backup_count", 3),
    )

    return Config(
        camera=camera,
        monitor=monitor,
        claude=claude,
        telegram=telegram,
        database=database,
        logging=logging_config,
        base_dir=base_dir,
    )
