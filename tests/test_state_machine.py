"""Tests for the bowl state machine."""

import pytest
from comiotrufa.state_machine import (
    BowlStateMachine,
    STATE_FOOD,
    STATE_EMPTY,
    STATE_UNKNOWN,
    EVENT_DOG_ATE,
    EVENT_BOWL_REFILLED,
    EVENT_INITIAL,
)


class TestBowlStateMachine:
    def test_initial_state_is_unknown(self):
        sm = BowlStateMachine()
        assert sm.current_state == STATE_UNKNOWN

    def test_custom_initial_state(self):
        sm = BowlStateMachine(initial_state=STATE_FOOD)
        assert sm.current_state == STATE_FOOD

    def test_debounce_requires_two_readings(self):
        sm = BowlStateMachine(initial_state=STATE_FOOD, debounce_threshold=2)

        # First "empty" reading — no transition yet
        event = sm.process_reading(STATE_EMPTY, 0.9, "img1.jpg")
        assert event is None
        assert sm.current_state == STATE_FOOD

        # Second "empty" reading — now transitions
        event = sm.process_reading(STATE_EMPTY, 0.95, "img2.jpg")
        assert event is not None
        assert event.event_type == EVENT_DOG_ATE
        assert event.previous_state == STATE_FOOD
        assert event.new_state == STATE_EMPTY
        assert sm.current_state == STATE_EMPTY

    def test_same_state_resets_pending(self):
        sm = BowlStateMachine(initial_state=STATE_FOOD, debounce_threshold=2)

        # One "empty" reading
        sm.process_reading(STATE_EMPTY, 0.9, "img1.jpg")

        # Back to "food" — resets pending
        event = sm.process_reading(STATE_FOOD, 0.9, "img2.jpg")
        assert event is None

        # Now one "empty" again — should need two more
        event = sm.process_reading(STATE_EMPTY, 0.9, "img3.jpg")
        assert event is None

    def test_low_confidence_ignored(self):
        sm = BowlStateMachine(initial_state=STATE_FOOD, debounce_threshold=2)

        # Low confidence readings don't count
        event = sm.process_reading(STATE_EMPTY, 0.3, "img1.jpg")
        assert event is None
        event = sm.process_reading(STATE_EMPTY, 0.4, "img2.jpg")
        assert event is None
        assert sm.current_state == STATE_FOOD

    def test_food_to_empty_is_dog_ate(self):
        sm = BowlStateMachine(initial_state=STATE_FOOD, debounce_threshold=1)
        event = sm.process_reading(STATE_EMPTY, 0.9, "img.jpg")
        assert event.event_type == EVENT_DOG_ATE

    def test_empty_to_food_is_refilled(self):
        sm = BowlStateMachine(initial_state=STATE_EMPTY, debounce_threshold=1)
        event = sm.process_reading(STATE_FOOD, 0.9, "img.jpg")
        assert event.event_type == EVENT_BOWL_REFILLED

    def test_unknown_to_food_is_initial(self):
        sm = BowlStateMachine(initial_state=STATE_UNKNOWN, debounce_threshold=1)
        event = sm.process_reading(STATE_FOOD, 0.9, "img.jpg")
        assert event.event_type == EVENT_INITIAL

    def test_unknown_to_empty_is_initial(self):
        sm = BowlStateMachine(initial_state=STATE_UNKNOWN, debounce_threshold=1)
        event = sm.process_reading(STATE_EMPTY, 0.9, "img.jpg")
        assert event.event_type == EVENT_INITIAL

    def test_no_event_when_state_unchanged(self):
        sm = BowlStateMachine(initial_state=STATE_FOOD, debounce_threshold=1)
        event = sm.process_reading(STATE_FOOD, 0.95, "img.jpg")
        assert event is None

    def test_confidence_takes_max(self):
        sm = BowlStateMachine(initial_state=STATE_FOOD, debounce_threshold=2)
        sm.process_reading(STATE_EMPTY, 0.7, "img1.jpg")
        event = sm.process_reading(STATE_EMPTY, 0.95, "img2.jpg")
        assert event.confidence == 0.95

    def test_full_cycle(self):
        """Test a complete eat → refill cycle."""
        sm = BowlStateMachine(initial_state=STATE_FOOD, debounce_threshold=2)

        # Dog eats
        sm.process_reading(STATE_EMPTY, 0.9, "img1.jpg")
        event = sm.process_reading(STATE_EMPTY, 0.9, "img2.jpg")
        assert event.event_type == EVENT_DOG_ATE
        assert sm.current_state == STATE_EMPTY

        # Owner refills
        sm.process_reading(STATE_FOOD, 0.85, "img3.jpg")
        event = sm.process_reading(STATE_FOOD, 0.9, "img4.jpg")
        assert event.event_type == EVENT_BOWL_REFILLED
        assert sm.current_state == STATE_FOOD
