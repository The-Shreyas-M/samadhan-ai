import math
import time
from datetime import datetime, timedelta
from collections import defaultdict
from sqlalchemy.orm import Session
from app.database import Complaint

# Per-IP recent submissions (in-memory rate limiter for demo)
_ip_timestamps = defaultdict(list)
_max_submissions_per_window = 5
_rate_window_seconds = 300


def check_rate_limit(ip: str) -> tuple:
    now = time.time()
    ip_timestamps = _ip_timestamps[ip]
    ip_timestamps[:] = [ts for ts in ip_timestamps if now - ts < _rate_window_seconds]
    if len(ip_timestamps) >= _max_submissions_per_window:
        return False, f"Too many complaints from this network in a short time ({len(ip_timestamps)} in 5 min). Possible spam - submission blocked."
    ip_timestamps.append(now)
    return True, None


def detect_spam(db: Session, raw_text: str, ip: str, photo_attached: bool, classification: dict, urgency_score: int) -> tuple:
    reasons = []

    # 1. Explicit LLM spam signal (embedded in classification by AI service)
    if classification.get("is_spam"):
        reasons.append(classification.get("spam_reason", "AI flagged this as spam/low-quality"))

    # 2. Very low urgency + nonsensical/short input heuristics
    normalized = (classification.get("normalized_text") or raw_text).strip().lower()

    gibberish = sum(1 for ch in raw_text if ch.isalpha()) < 4
    if gibberish:
        reasons.append("Input appears to be gibberish/random characters (attacker spam signature)")

    if gibberish and not photo_attached:
        reasons.append("No photo evidence attached and input is not meaningful - treated as spam")

    # 3. Duplicate spam burst: many near-identical complaints in quick succession
    from app.ai_service import compute_embedding, find_duplicate
    recent = db.query(Complaint).filter(
        Complaint.created_at >= datetime.utcnow() - timedelta(hours=1)
    ).all()
    if recent:
        emb = compute_embedding(raw_text)
        is_dup, parent_id, score = find_duplicate(emb, recent, threshold=0.82)
        near_dup = sum(1 for r in recent if r.embedding and score_against(r.embedding, emb) >= 0.82)
        if near_dup >= 3:
            reasons.append(f"Spam burst detected: {near_dup} near-identical complaints posted recently")

    # 4. Same IP + no photo + very fast repeat is handled by rate limiter separately

    is_flagged = len(reasons) >= 1
    reason = "; ".join(reasons) if reasons else None
    return is_flagged, reason


def score_against(stored_embedding_str: str, new_emb) -> float:
    import numpy as np
    if not stored_embedding_str:
        return 0.0
    stored = np.array([float(x) for x in stored_embedding_str.split(",")])
    return float(np.dot(new_emb, stored) / (np.linalg.norm(new_emb) * np.linalg.norm(stored)))


def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def verify_photo_location(photo_lat, photo_lon, complaint_lat, complaint_lon, max_km=0.5) -> tuple:
    """Match geotagged photo location to the reported complaint location."""
    if photo_lat is None or photo_lon is None:
        return False, "Photo has no geotag metadata - cannot verify location"
    d = haversine(photo_lat, photo_lon, complaint_lat, complaint_lon)
    if d <= max_km:
        return True, f"Photo geotag matches complaint location ({round(d*1000)}m away)"
    return False, f"Photo geotag is {round(d,2)}km from reported location - possible mismatch"
