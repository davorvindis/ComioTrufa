"""Camera capture module for ComioTrufa.

Uses picamera2 (Raspberry Pi Camera) with a fallback to fswebcam for USB cameras.
On non-Pi systems (dev/test), can use a dummy capture mode.
"""

import logging
import subprocess
from datetime import datetime
from pathlib import Path

from .config import CameraConfig

logger = logging.getLogger(__name__)


class Camera:
    def __init__(self, config: CameraConfig):
        self.config = config
        self.images_dir = Path(config.images_dir)
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self._picamera = None
        self._init_camera()

    def _init_camera(self):
        """Try to initialize picamera2. Falls back to libcamera-still CLI."""
        try:
            from picamera2 import Picamera2
            self._picamera = Picamera2()
            self._picamera.configure(
                self._picamera.create_still_configuration(
                    main={"size": self.config.resolution}
                )
            )
            logger.info("Camera initialized with picamera2")
        except (ImportError, RuntimeError) as e:
            logger.warning(f"picamera2 not available ({e}), will use libcamera-still CLI")
            self._picamera = None

    def capture(self) -> str:
        """Capture a photo and return the file path.

        Returns:
            Absolute path to the captured JPEG image.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"bowl_{timestamp}.jpg"
        filepath = self.images_dir / filename

        if self._picamera:
            self._capture_picamera(filepath)
        else:
            self._capture_cli(filepath)

        logger.info(f"Photo captured: {filepath}")
        return str(filepath)

    def _capture_picamera(self, filepath: Path):
        """Capture using picamera2 Python library."""
        self._picamera.start()
        self._picamera.capture_file(str(filepath))
        self._picamera.stop()

    def _capture_cli(self, filepath: Path):
        """Capture using libcamera-still command line tool."""
        cmd = [
            "libcamera-still",
            "-o", str(filepath),
            "--width", str(self.config.resolution[0]),
            "--height", str(self.config.resolution[1]),
            "--quality", str(self.config.image_quality),
            "--nopreview",
            "--immediate",
            "--rotation", str(self.config.rotation),
        ]
        try:
            subprocess.run(cmd, capture_output=True, check=True, timeout=15)
        except FileNotFoundError:
            raise RuntimeError(
                "No camera available. Install picamera2 or libcamera-still."
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("Camera capture timed out (15s)")

    def close(self):
        """Release camera resources."""
        if self._picamera:
            try:
                self._picamera.close()
            except Exception:
                pass
