"""Claude Vision API integration for ComioTrufa.

Sends bowl photos to Claude and gets structured state analysis.
"""

import base64
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import anthropic

from .config import ClaudeConfig

logger = logging.getLogger(__name__)

ANALYSIS_PROMPT = """Mira esta foto de un plato de comida para perro. Analiza y responde SOLO con JSON:

{
  "state": "food" o "empty",
  "confidence": 0.0 a 1.0,
  "description": "breve descripcion de lo que ves"
}

Reglas:
- "food" significa que hay comida visible (croquetas, comida humeda, etc.) en el plato
- "empty" significa que el plato esta vacio o solo tiene agua/residuos minimos
- confidence debe reflejar que tan seguro estas (1.0 = totalmente seguro)
- Si el plato no es visible o la imagen no es clara, usa confidence < 0.5
- Responde SOLO el JSON, sin texto adicional
"""


@dataclass
class VisionResult:
    state: str  # "food" or "empty"
    confidence: float
    description: str
    raw_response: str


class VisionAnalyzer:
    def __init__(self, config: ClaudeConfig):
        self.config = config
        self.client = anthropic.Anthropic(api_key=config.api_key)

    def analyze(self, image_path: str, max_retries: int = 3) -> Optional[VisionResult]:
        """Analyze a bowl photo and return the detected state.

        Args:
            image_path: Path to the JPEG image file.
            max_retries: Number of retry attempts on failure.

        Returns:
            VisionResult with state and confidence, or None on complete failure.
        """
        image_data = self._load_image(image_path)
        if not image_data:
            return None

        for attempt in range(max_retries):
            try:
                return self._call_api(image_data)
            except anthropic.RateLimitError:
                wait = 2 ** (attempt + 1)
                logger.warning(f"Rate limited, retrying in {wait}s...")
                time.sleep(wait)
            except anthropic.APIStatusError as e:
                if e.status_code >= 500:
                    wait = 2 ** (attempt + 1)
                    logger.warning(f"API error {e.status_code}, retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    logger.error(f"API client error: {e}")
                    return None
            except anthropic.APITimeoutError:
                wait = 2 ** (attempt + 1)
                logger.warning(f"API timeout, retrying in {wait}s...")
                time.sleep(wait)
            except Exception as e:
                logger.error(f"Unexpected error in vision analysis: {e}")
                return None

        logger.error(f"All {max_retries} retries failed for {image_path}")
        return None

    def _load_image(self, image_path: str) -> Optional[str]:
        """Load and base64-encode an image file."""
        path = Path(image_path)
        if not path.exists():
            logger.error(f"Image not found: {image_path}")
            return None

        with open(path, "rb") as f:
            return base64.standard_b64encode(f.read()).decode("utf-8")

    def _call_api(self, image_data: str) -> VisionResult:
        """Make the Claude Vision API call."""
        message = self.client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": image_data,
                            },
                        },
                        {
                            "type": "text",
                            "text": ANALYSIS_PROMPT,
                        },
                    ],
                }
            ],
        )

        raw_text = message.content[0].text
        return self._parse_response(raw_text)

    def _parse_response(self, raw_text: str) -> VisionResult:
        """Parse the JSON response from Claude."""
        # Try to extract JSON from the response
        text = raw_text.strip()

        # Handle markdown code blocks
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse JSON response: {raw_text}")
            return VisionResult(
                state="unknown",
                confidence=0.0,
                description="Failed to parse API response",
                raw_response=raw_text,
            )

        state = data.get("state", "unknown")
        if state not in ("food", "empty"):
            state = "unknown"

        confidence = float(data.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))

        return VisionResult(
            state=state,
            confidence=confidence,
            description=data.get("description", ""),
            raw_response=raw_text,
        )
