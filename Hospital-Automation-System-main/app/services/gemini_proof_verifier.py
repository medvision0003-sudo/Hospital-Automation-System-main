import base64
import json
import mimetypes
import os
from pathlib import Path

import requests


class VerificationUnavailable(RuntimeError):
    """Raised when Gemini cannot provide a trustworthy verification result."""


def analyze_task_proof(
    image_path: Path,
    task_name: str,
    task_description: str | None,
) -> dict:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    demo_mode = os.getenv("DEMO_MODE", "false").strip().lower() == "true"
    if not api_key:
        if demo_mode:
            normalized_name = (task_name or "task").strip()
            reason = (
                "DEMO_MODE is active; the submitted image is linked to the assigned "
                f"work item '{normalized_name}'. Image contents were not analyzed."
            )
            return {
                "decision": "VERIFIED",
                "confidence": 0.92,
                "reason": reason,
                "provider": "DEMO",
            }
        raise VerificationUnavailable(
            "GEMINI_API_KEY is not configured; proof requires human review."
        )

    model = os.getenv("GEMINI_VISION_MODEL", "gemini-2.5-flash").strip()
    mime_type, _ = mimetypes.guess_type(image_path.name)
    if not mime_type or not mime_type.startswith("image/"):
        raise VerificationUnavailable("Submitted proof is not a supported image.")
    try:
        image_data = base64.b64encode(image_path.read_bytes()).decode("ascii")
    except OSError as exc:
        raise VerificationUnavailable(
            f"Submitted proof image could not be read: {exc}"
        ) from exc

    prompt = (
        "Assess whether the image is meaningful visual evidence that the specific "
        "hospital work item below was completed. Do not infer completion merely "
        "from the existence of an image. If the image is unrelated, return REJECTED. "
        "If image quality or evidence is ambiguous, return NEEDS_REVIEW. "
        "Do not identify people or infer sensitive patient information. "
        "Return only JSON with decision (VERIFIED, REJECTED, or NEEDS_REVIEW), "
        "confidence (number from 0 to 1), and reason (brief string).\n\n"
        f"TASK: {task_name}\n"
        f"REQUIREMENTS / DESCRIPTION: {task_description or 'No additional details provided.'}"
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": image_data,
                        }
                    },
                ]
            }
        ],
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": 0.1,
        },
    }

    try:
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": api_key},
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        response_body = response.json()
        text = response_body["candidates"][0]["content"]["parts"][0]["text"]
        result = json.loads(text)
    except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
        raise VerificationUnavailable(
            f"Gemini verification failed or returned invalid JSON: {exc}"
        ) from exc

    decision = result.get("decision")
    confidence = result.get("confidence")
    reason = result.get("reason")
    if (
        decision not in {"VERIFIED", "REJECTED", "NEEDS_REVIEW"}
        or isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= confidence <= 1
        or not isinstance(reason, str)
        or not reason.strip()
    ):
        raise VerificationUnavailable("Gemini returned an invalid verification result.")

    return {
        "decision": decision,
        "confidence": float(confidence),
        "reason": reason.strip()[:1000],
        "provider": "GEMINI",
    }
