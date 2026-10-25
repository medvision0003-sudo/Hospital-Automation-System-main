import base64
import json

import pytest

from app.services.gemini_proof_verifier import (
    VerificationUnavailable,
    analyze_task_proof,
)


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


def test_gemini_verifier_sends_image_and_parses_decision(tmp_path, monkeypatch):
    image_path = tmp_path / "proof.jpg"
    image_bytes = b"test-image-bytes"
    image_path.write_bytes(image_bytes)
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-key")
    captured = {}

    def post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "decision": "VERIFIED",
                                            "confidence": 0.91,
                                            "reason": "The image shows the requested work area.",
                                        }
                                    )
                                }
                            ]
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("app.services.gemini_proof_verifier.requests.post", post)
    result = analyze_task_proof(image_path, "Clean ICU Bed 12", "Clean the bed area.")
    assert result == {
        "decision": "VERIFIED",
        "confidence": 0.91,
        "reason": "The image shows the requested work area.",
        "provider": "GEMINI",
    }
    sent_image = captured["json"]["contents"][0]["parts"][1]["inline_data"]["data"]
    assert base64.b64decode(sent_image) == image_bytes
    assert captured["headers"]["x-goog-api-key"] == "test-only-key"


def test_gemini_verifier_fails_explicitly_when_unconfigured(tmp_path, monkeypatch):
    image_path = tmp_path / "proof.jpg"
    image_path.write_bytes(b"test")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(VerificationUnavailable, match="not configured"):
        analyze_task_proof(image_path, "Clean ICU Bed 12", None)


def test_demo_verifier_uses_backend_provider_without_gemini(tmp_path, monkeypatch):
    image_path = tmp_path / "proof.jpg"
    image_path.write_bytes(b"demo image")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("DEMO_MODE", "true")

    result = analyze_task_proof(image_path, "Clean ICU Bed 12", "Clean the bed area.")

    assert result["decision"] == "VERIFIED"
    assert result["confidence"] == 0.92
    assert result["provider"] == "DEMO"
    assert "contents were not analyzed" in result["reason"]
