"""Tests for the vision module response parsing."""

from comiotrufa.vision import VisionAnalyzer
from comiotrufa.config import ClaudeConfig


class TestVisionParser:
    """Test the JSON response parsing logic."""

    def setup_method(self):
        # Create analyzer with dummy config (won't actually call API)
        config = ClaudeConfig(api_key="test-key")
        self.analyzer = VisionAnalyzer(config)

    def test_parse_valid_food_response(self):
        raw = '{"state": "food", "confidence": 0.95, "description": "bowl full of kibble"}'
        result = self.analyzer._parse_response(raw)
        assert result.state == "food"
        assert result.confidence == 0.95
        assert result.description == "bowl full of kibble"

    def test_parse_valid_empty_response(self):
        raw = '{"state": "empty", "confidence": 0.88, "description": "empty metal bowl"}'
        result = self.analyzer._parse_response(raw)
        assert result.state == "empty"
        assert result.confidence == 0.88

    def test_parse_markdown_code_block(self):
        raw = '```json\n{"state": "food", "confidence": 0.9, "description": "has food"}\n```'
        result = self.analyzer._parse_response(raw)
        assert result.state == "food"
        assert result.confidence == 0.9

    def test_parse_invalid_json(self):
        raw = "I can see a bowl with food in it"
        result = self.analyzer._parse_response(raw)
        assert result.state == "unknown"
        assert result.confidence == 0.0

    def test_parse_invalid_state(self):
        raw = '{"state": "half-full", "confidence": 0.7, "description": "some food"}'
        result = self.analyzer._parse_response(raw)
        assert result.state == "unknown"

    def test_confidence_clamped(self):
        raw = '{"state": "food", "confidence": 1.5, "description": "test"}'
        result = self.analyzer._parse_response(raw)
        assert result.confidence == 1.0

        raw = '{"state": "food", "confidence": -0.5, "description": "test"}'
        result = self.analyzer._parse_response(raw)
        assert result.confidence == 0.0

    def test_missing_fields_handled(self):
        raw = '{"state": "food"}'
        result = self.analyzer._parse_response(raw)
        assert result.state == "food"
        assert result.confidence == 0.0
        assert result.description == ""
