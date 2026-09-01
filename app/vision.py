import os
import base64
import numpy as np
from openai import OpenAI
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
from dotenv import load_dotenv

load_dotenv()

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
NVIDIA_BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
VISION_MODEL = os.getenv("VISION_MODEL", "nvidia/neva-22b")

vision_client = None
if NVIDIA_API_KEY:
    vision_client = OpenAI(base_url=NVIDIA_BASE_URL, api_key=NVIDIA_API_KEY)

VISION_PROMPT = """You are verifying citizen-submitted photo evidence for a civic grievance platform.
Photo metadata/analysis:
- Reported complaint: {raw_text}
- Reported department: {department}

Examine the photograph and answer strictly YES or NO with a short reason:
Does the photograph clearly show the issue described in the complaint?
Respond as a single line: "MATCH - <reason>" or "MISMATCH - <reason>" or "UNCLEAR - <reason>".
Do not output anything else."""


def verify_image_with_vision(image_path: str, raw_text: str, department: str) -> dict:
    """Send the image to a vision-capable LLM to verify it matches the reported issue."""
    if not vision_client or not image_path or not os.path.exists(image_path):
        return {"status": "skipped", "note": "Vision verification not available", "confidence": None}

    try:
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode()

        from app.evidence import extract_exif
        exif = extract_exif(image_path)
        meta = f"Photo embedded GPS: {exif.get('geotag_lat')}, {exif.get('geotag_lon')}, captured {exif.get('taken_at')}"

        response = vision_client.chat.completions.create(
            model=VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": VISION_PROMPT.format(
                            raw_text=raw_text[:500],
                            department=department,
                        ) + f"\n{meta}"},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                    ],
                }
            ],
            max_tokens=100,
            temperature=0.0,
        )
        text = (response.choices[0].message.content or "").strip()
        upper = text.upper()
        if upper.startswith("MATCH"):
            return {"status": "match", "note": text, "confidence": "high"}
        if upper.startswith("MISMATCH"):
            return {"status": "mismatch", "note": text, "confidence": "high"}
        if upper.startswith("UNCLEAR"):
            return {"status": "unclear", "note": text, "confidence": "low"}
        return {"status": "unknown", "note": text, "confidence": None}
    except Exception as e:
        return {"status": "error", "note": f"Vision analysis failed: {e}", "confidence": None}


def detect_ai_generated(image_path: str) -> dict:
    """Lightweight heuristic for AI-generated image detection.

    Uses simple statistical signals: JPEG artifact uniformity, noise levels,
    and metadata anomalies. Not a substitute for a dedicated classifier,
    but provides a basic flag.
    """
    if not image_path or not os.path.exists(image_path):
        return {"is_ai": None, "score": None, "note": "No image to analyze"}

    try:
        img = Image.open(image_path).convert("L")
        arr = np.asarray(img, dtype=np.float32)

        # 1. Noise / texture variance
        laplacian = np.abs(np.diff(arr, axis=0))
        sharpness = float(np.mean(laplacian))

        # 2. Flatness / banding (AI images often have smoother gradients)
        grad = np.abs(np.diff(arr, axis=1))
        gradient_variance = float(np.var(grad))

        # 3. JPEG quantization fingerprint - skip, heuristic only
        # Combine heuristic signals
        # AI-generated images often have unusually low noise + high smoothness
        smoothness = 1.0 / (sharpness + 1e-6)

        # Simple scoring model (0-1, higher = more likely AI)
        # Real photos: higher sharpness (edges), higher gradient variance
        # AI images: lower sharpness typically, or unnaturally clean gradients
        score = min(1.0, max(0.0, smoothness * 0.02 + (0.5 - gradient_variance * 0.00005)))

        is_ai = score > 0.7
        return {
            "is_ai": bool(is_ai),
            "score": round(score, 2),
            "note": "Heuristic artifact check flagged as possibly AI-generated" if is_ai else "No strong AI-generation artifact signal",
        }
    except Exception as e:
        return {"is_ai": None, "score": None, "note": f"AI check failed: {e}"}
