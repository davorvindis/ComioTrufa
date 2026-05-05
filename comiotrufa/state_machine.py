"""Bowl state machine with debounce logic for ComioTrufa."""

from dataclasses import dataclass
from typing import Optional

# Valid states
STATE_FOOD = "food"
STATE_EMPTY = "empty"
STATE_UNKNOWN = "unknown"

# Event types
EVENT_DOG_ATE = "dog_ate"
EVENT_BOWL_REFILLED = "bowl_refilled"
EVENT_INITIAL = "initial"


@dataclass
class StateEvent:
    previous_state: str
    new_state: str
    event_type: str
    confidence: float
    image_path: str


class BowlStateMachine:
    """Tracks bowl state and detects transitions with debounce.

    Requires `debounce_threshold` consecutive identical readings
    before confirming a state change. This prevents false positives
    from shadows, the dog blocking the camera, etc.
    """

    def __init__(self, initial_state: Optional[str] = None, debounce_threshold: int = 2):
        self.current_state = initial_state or STATE_UNKNOWN
        self.debounce_threshold = debounce_threshold
        self._pending_state: Optional[str] = None
        self._pending_count: int = 0
        self._pending_confidence: float = 0.0
        self._pending_image: str = ""

    def process_reading(self, new_state: str, confidence: float,
                        image_path: str) -> Optional[StateEvent]:
        """Process a new reading and return an event if a state transition occurs.

        Args:
            new_state: The detected state ("food" or "empty")
            confidence: Confidence score from the vision model (0.0-1.0)
            image_path: Path to the image that produced this reading

        Returns:
            StateEvent if a confirmed transition happened, None otherwise.
        """
        # Low confidence readings are unreliable — ignore them
        if confidence < 0.5:
            self._pending_state = None
            self._pending_count = 0
            return None

        # Same as current state — no transition happening
        if new_state == self.current_state:
            self._pending_state = None
            self._pending_count = 0
            return None

        # Different from current state — accumulate pending readings
        if new_state == self._pending_state:
            self._pending_count += 1
            self._pending_confidence = max(self._pending_confidence, confidence)
            self._pending_image = image_path
        else:
            self._pending_state = new_state
            self._pending_count = 1
            self._pending_confidence = confidence
            self._pending_image = image_path

        # Check if we've reached the debounce threshold
        if self._pending_count >= self.debounce_threshold:
            event = self._transition(new_state)
            self._pending_state = None
            self._pending_count = 0
            return event

        return None

    def _transition(self, new_state: str) -> StateEvent:
        """Execute a state transition and return the event."""
        previous = self.current_state
        self.current_state = new_state

        if previous == STATE_UNKNOWN:
            event_type = EVENT_INITIAL
        elif previous == STATE_FOOD and new_state == STATE_EMPTY:
            event_type = EVENT_DOG_ATE
        elif previous == STATE_EMPTY and new_state == STATE_FOOD:
            event_type = EVENT_BOWL_REFILLED
        else:
            event_type = EVENT_INITIAL

        return StateEvent(
            previous_state=previous,
            new_state=new_state,
            event_type=event_type,
            confidence=self._pending_confidence,
            image_path=self._pending_image,
        )
