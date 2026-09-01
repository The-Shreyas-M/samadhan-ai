import os
import json
import re
import logging
import numpy as np
from openai import OpenAI
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv

from app.departments import DEPARTMENTS, DEPARTMENT_MAP, VALID_DEPARTMENTS

load_dotenv()

logger = logging.getLogger("samadhan.ai_service")

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
NVIDIA_BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3-super-120b-a12b")

embedding_model = SentenceTransformer("all-MiniLM-L6-v2")

llm_client = None
if NVIDIA_API_KEY:
    llm_client = OpenAI(base_url=NVIDIA_BASE_URL, api_key=NVIDIA_API_KEY)

VALID_DEPARTMENTS_STR = ", ".join([f'{d["name"]} ({d["key"]})' for d in DEPARTMENTS])

SYSTEM_PROMPT = f"""You are a civic grievance classification engine for an Indian city. You receive a citizen complaint in English, Hindi, or Hinglish.

Your tasks:
1. Normalize/translate the complaint into clean English.
2. Classify it into exactly one department from the list below.
3. Give a short category within that department (e.g. "Murder", "Fire", "Water contamination").
4. Assign a priority level.
5. Assign an urgency score (1-100).
6. Recommend a brief 1-line dispatch action.
7. Assess whether the complaint looks SPAM, fake, nonsensical, or an automated attack. Set "is_spam" true and give a short "spam_reason" if so.

Valid departments (name, key):
{VALID_DEPARTMENTS_STR}

Valid priorities: Critical, High, Medium, Low

CRITICAL CLASSIFICATION RULES — follow these EXACTLY:
- "heart attack", "cardiac", "chest pain", "can't breathe", "breathing difficulty", "stroke", "severe bleeding", "unconscious person", "medical emergency", "ambulance needed" → Public Health & Medical (health)
- "gas leak", "fire", "burning", "building collapse", "rescue needed" → Fire & Emergency Services (fire)
- "murder", "fight", "assault", "theft", "robbery", "stolen", "crime" → Police & Law Enforcement (police)
- "water not coming", "water supply", "pipeline", "drainage", "sewerage" → Water Supply & Sewerage (water)
- "pothole", "road damage", "broken road", "street light" → Roads & Infrastructure (roads)
- "garbage", "trash", "waste", "sewage smell", "sanitation" → Solid Waste & Sanitation (sanitation)
- "power cut", "electricity", "transformer", "wire down" → Electricity & Power (electricity)
- "illegal construction", "encroachment", "building violation" → Urban Planning & Building (planning)
- "pollution", "tree cutting", "stray animals" → Environment & Green (environment)
- "bus", "traffic", "parking", "signal" → Public Transport & Traffic (transport)
- "school", "college", "mid-day meal" → Education (education)
- "homeless", "hungry", "disabled", "elder care" → Social Welfare (social)

IMPORTANT: A "heart attack" or "chest pain" is a MEDICAL emergency, NOT a crime/police matter. Always route health emergencies to the Public Health & Medical department.

Examples:
- "heart attack ho raha hai" → Public Health & Medical (health), Critical
- "chest pain and breathing difficulty" → Public Health & Medical (health), Critical
- "gas leak" → Fire & Emergency Services (fire)
- "murder", "fight", "theft" → Police & Law Enforcement (police)
- "water not coming" → Water Supply & Sewerage (water)
- "forest fire" → Fire & Emergency Services (fire)
- "homeless hungry" → Social Welfare (social)
- "asdkjgh asdkjhg asd" → is_spam true

Respond with ONLY valid JSON, no markdown, no explanation:
{{
  "normalized_text": "Clean English summary",
  "department": "Full Department Name",
  "department_key": "key",
  "category": "Short category",
  "priority": "Priority Level",
  "urgency_score": 85,
  "action_recommended": "Brief dispatch action",
  "is_spam": false,
  "spam_reason": null
}}"""

# Keyword-based fallback map (English/Hindi/Hinglish keywords -> department_key)
# ORDER MATTERS: multi-word / specific phrases MUST come before short generic words.
# Medical/emergency keywords checked FIRST so "heart attack" doesn't match police "attack".
KEYWORD_MAP = [
    ("health", ["heart attack", "cardiac", "chest pain", "can't breathe", "breathing difficulty",
                "saans", "breathless", "stroke", "severe bleeding", "unconscious", "ambulance",
                "medical emergency", "heart", "dil ka daura", "sans ki taklif",
                "hospital", "doctor", "disease", "dengue", "malaria", "mosquito", "health",
                "medicine", "aspatal", "bimari", "beemar"]),
    ("fire", ["gas leak", "gas l", "fire", "aag", "aag lag", "building collapse", "rescue"]),
    ("police", ["murder", "theft", "robbery", "stolen", "assault", "fight", "crime",
                "forc", "chori", "loot", "hatya", "maar pitai", "thug", "bns", "pistol", "gund", "haras",
                "sim", "cyber", "fraud", "police", " FIR"]),
    ("water", ["water", "paani", "supply", "pipe", "sewer", "naali", "drain", "jal"]),
    ("roads", ["pothole", "road", "gadda", "sadak", "footpath", "bridge", "flyover", "street light"]),
    ("sanitation", ["garbage", "kachra", "trash", "waste", "sewage", "ganda", "smell", "sweep", "sanit", "bhangi"]),
    ("electricity", ["bijli", "electric", "light", "power cut", "current", "transformer", "wire", "pole", "fuse"]),
    ("planning", ["building", "construction", "illegal", "encroach", "plot", "tower", "makan", "naksha"]),
    ("environment", ["tree", "park", "pollution", "smoke", "plastic", "garden", "ped", "animals", "stray"]),
    ("transport", ["bus", "traffic", "signal", "parking", "auto", "congestion", "jam", "vehicle"]),
    ("education", ["school", "college", "student", "teacher", "pustak", "vidyalaya", "mid-day meal"]),
    ("social", ["homeless", "hungry", "bio", "beggar", "disabled", "orphan", "bhaav", "roti", "aasra"]),
]


def keyword_classify(raw_text: str) -> dict:
    text = raw_text.lower()
    alphabetic = sum(1 for ch in raw_text if ch.isalpha())
    gibberish = alphabetic < 4

    # Sensible category / priority / urgency per department when the LLM is down.
    FALLBACK_PROFILE = {
        "health":     ("Medical Emergency",       "Critical", 90),
        "fire":       ("Fire & Gas Leak",         "Critical", 88),
        "police":     ("Law & Order",             "High",     78),
        "water":      ("Water Supply / Drainage", "High",     65),
        "electricity":("Power Outage",            "High",     68),
        "transport":  ("Traffic & Transport",     "High",     62),
        "social":     ("Social Welfare",          "High",     60),
        "sanitation": ("Solid Waste",             "Medium",   52),
        "roads":      ("Roads & Infrastructure",  "Medium",   55),
        "planning":   ("Construction / Encroachment", "Medium", 55),
        "environment":("Environment & Pollution", "Medium",   50),
        "education":  ("Education",               "Medium",   50),
    }

    for key, keywords in KEYWORD_MAP:
        if any(kw in text for kw in keywords):
            dept = DEPARTMENT_MAP[key]
            category, priority, urgency = FALLBACK_PROFILE.get(
                key, ("General", "Medium", 55)
            )
            return {
                "department": dept["name"],
                "department_key": key,
                "category": category,
                "normalized_text": raw_text.strip(),
                "priority": priority,
                "urgency_score": urgency,
                "action_recommended": f"Dispatch {dept['short']} team for assessment.",
                "is_spam": gibberish,
                "spam_reason": "Input appears to be gibberish" if gibberish else None,
            }
    dept = DEPARTMENT_MAP["roads"]
    return {
        "department": dept["name"],
        "department_key": "roads",
        "category": "General",
        "normalized_text": raw_text.strip(),
        "priority": "Medium",
        "urgency_score": 50,
        "action_recommended": "Route to relevant department for review.",
        "is_spam": gibberish,
        "spam_reason": "Input appears to be gibberish" if gibberish else None,
    }


def _resolve_department(name: str, key: str = None) -> tuple:
    if key and key in DEPARTMENT_MAP:
        return DEPARTMENT_MAP[key]
    if name:
        for d in DEPARTMENTS:
            if d["name"].lower() == name.lower() or d["short"].lower() in name.lower():
                return d
    return None


def _normalize_classification(data: dict, raw_text: str) -> dict:
    dept = _resolve_department(data.get("department"), data.get("department_key"))
    if dept is not None:
        data["department"] = dept["name"]
        data["department_key"] = dept["key"]
    else:
        data["department"] = DEPARTMENT_MAP["roads"]["name"]
        data["department_key"] = "roads"
    data["category"] = data.get("category") or "General"
    data.setdefault("normalized_text", raw_text.strip())
    priority = str(data.get("priority", "")).strip().capitalize()
    if priority not in ("Critical", "High", "Medium", "Low"):
        priority = "Medium"
        data.pop("urgency_score", None)
    data["priority"] = priority
    try:
        data["urgency_score"] = int(data.get("urgency_score", 50))
    except (TypeError, ValueError):
        data["urgency_score"] = 50
    data["urgency_score"] = max(1, min(100, data["urgency_score"]))
    data.setdefault("is_spam", False)
    data.setdefault("spam_reason", None)
    return data


def classify_complaint(raw_text: str) -> dict:
    if not llm_client:
        logger.warning("LLM client not configured; using keyword fallback")
        return keyword_classify(raw_text)

    try:
        response = llm_client.chat.completions.create(
            model=NVIDIA_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": raw_text},
            ],
            temperature=0.2,
            max_tokens=512,
        )
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
        data = json.loads(content)
        return _normalize_classification(data, raw_text)
    except Exception as exc:
        logger.warning(
            "LLM classification failed (model=%s) for text=%r; using keyword fallback: %s",
            NVIDIA_MODEL, (raw_text[:80] + "...") if len(raw_text) > 80 else raw_text, exc,
        )
        return keyword_classify(raw_text)


def compute_embedding(text: str) -> np.ndarray:
    return embedding_model.encode(text)


def find_duplicate(new_embedding: np.ndarray, existing_records: list, threshold: float = 0.82):
    best_match = None
    best_score = 0.0

    for record in existing_records:
        if not record.embedding:
            continue
        stored = np.array([float(x) for x in record.embedding.split(",")])
        similarity = np.dot(new_embedding, stored) / (
            np.linalg.norm(new_embedding) * np.linalg.norm(stored)
        )
        if similarity > best_score:
            best_score = similarity
            best_match = record

    if best_score >= threshold:
        return True, best_match.id, best_score
    return False, None, best_score
