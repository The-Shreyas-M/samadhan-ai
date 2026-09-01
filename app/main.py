import os
import json
import uuid
import datetime
from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from app.database import get_db, init_db, Complaint, User, SessionLocal
from app.ai_service import classify_complaint, compute_embedding, find_duplicate
from app.seed_data import seed_database, seed_users
from app.auth import get_current_user, require_auth, require_admin, SESSION_KEY
from app.departments import DEPARTMENTS, DEPARTMENT_MAP
from app.spam import check_rate_limit, detect_spam, verify_photo_location
from app.evidence import extract_exif, save_photo_base64

load_dotenv()

app = FastAPI(title="Samadhan AI", description="Grievance Classification & Duplicate Detection Engine")

app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY", "samadhan-dev-secret"))

templates = Jinja2Templates(directory="app/templates")

import os as _os
_os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

PRIORITY_CLASSES = {
    "Critical": "bg-red-500/20 text-red-400 border border-red-500/40",
    "High": "bg-orange-500/20 text-orange-400 border border-orange-500/40",
    "Medium": "bg-amber-500/20 text-amber-400 border border-amber-500/40",
    "Low": "bg-emerald-500/20 text-emerald-400 border border-emerald-500/40",
}


@app.on_event("startup")
def on_startup():
    init_db()
    db = SessionLocal()
    try:
        seed_database(db)
        seed_users(db)
    finally:
        db.close()


def make_tracking_id():
    return "SAM-" + uuid.uuid4().hex[:8].upper()


def photo_url(photo_path):
    """Return the public /uploads/... URL for a stored photo_path."""
    if not photo_path:
        return None
    base = os.path.basename(photo_path.replace("\\", "/"))
    return f"/uploads/{base}"


templates.env.filters["photo_url"] = photo_url


# ---------------- Public / Citizen ----------------

@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    recent = db.query(Complaint).order_by(Complaint.created_at.desc()).limit(8).all()
    totals = get_metrics(db)
    dept_breakdown = get_dept_breakdown(db)
    return templates.TemplateResponse(request, "index.html", {
        "complaints": recent,
        "departments": DEPARTMENTS,
        "totals": totals,
        "dept_breakdown": dept_breakdown,
    })


@app.get("/track", response_class=HTMLResponse)
def track_page(request: Request, tracking_id: str = None, db: Session = Depends(get_db)):
    if tracking_id:
        complaint = db.query(Complaint).filter(Complaint.tracking_id == tracking_id.strip().upper()).first()
        return templates.TemplateResponse(request, "track.html", {
            "complaint": complaint,
            "error": None if complaint else f"No complaint found for ID {tracking_id}",
            "status_history": (json.loads(complaint.status_history) if complaint and complaint.status_history else []),
        })
    return templates.TemplateResponse(request, "track.html", {"complaint": None, "error": None, "status_history": []})


@app.get("/track/{tracking_id}", response_class=HTMLResponse)
def track_lookup(request: Request, tracking_id: str, db: Session = Depends(get_db)):
    complaint = db.query(Complaint).filter(Complaint.tracking_id == tracking_id.upper()).first()
    if not complaint:
        return templates.TemplateResponse(request, "track.html", {
            "complaint": None,
            "error": f"No complaint found for ID {tracking_id}",
        })
    status_history = []
    if complaint.status_history:
        try:
            status_history = json.loads(complaint.status_history)
        except Exception:
            status_history = []
    return templates.TemplateResponse(request, "track.html", {
        "complaint": complaint,
        "error": None,
        "status_history": status_history,
    })


@app.post("/api/complaints/submit", response_class=HTMLResponse)
def submit_complaint(
    request: Request,
    raw_text: str = Form(...),
    lat: float = Form(...),
    lon: float = Form(...),
    photo: str = Form(None),
    db: Session = Depends(get_db),
):
    client_ip = request.client.host if request.client else "unknown"

    # --- Anti-spam: rate limit per IP ---
    allowed, rate_msg = check_rate_limit(client_ip)
    if not allowed:
        return templates.TemplateResponse(request, "partials/submit_result.html", {
            "complaint": None, "is_spam_true": True,
            "spam_message": rate_msg, "action_recommended": None,
        })

    classification = classify_complaint(raw_text)

    # --- Photo evidence (in-browser camera capture, base64 JPEG with GPS/timestamp EXIF) ---
    photo_path = None
    photo_full = None
    photo_geo = {}
    evidence_verified = False
    evidence_note = None
    photo_attached = bool(photo and photo.startswith("data:image"))
    if photo_attached:
        photo_path = save_photo_base64(photo)
        photo_full = os.path.join("uploads", photo_path)
        photo_geo = extract_exif(photo_full)
        if photo_geo.get("geotag_lat") is not None:
            ok, note = verify_photo_location(
                photo_geo["geotag_lat"], photo_geo["geotag_lon"],
                lat, lon,
            )
            evidence_verified = ok
            evidence_note = note
        else:
            evidence_note = "Photo captured but location metadata missing - location not verifiable"

    # --- Spam / suspicious detection ---
    is_flagged, flag_reason = detect_spam(
        db, raw_text, client_ip,
        photo_attached=photo_attached,
        classification=classification,
        urgency_score=classification.get("urgency_score", 50),
    )
    if classification.get("is_spam"):
        is_flagged = True
        flag_reason = (flag_reason or "") + ("; " if flag_reason else "") + (classification.get("spam_reason") or "AI flagged as spam")

    # --- Vision verification for critical/high complaints ---
    vision_result = None
    ai_gen_result = None
    if photo_attached and classification.get("priority") in ("Critical", "High"):
        from app.vision import verify_image_with_vision, detect_ai_generated
        vision_result = verify_image_with_vision(
            photo_full, raw_text, classification.get("department", "")
        )
        ai_gen_result = detect_ai_generated(photo_full)

        vision_notes = []
        if vision_result and vision_result.get("status") == "mismatch":
            is_flagged = True
            vision_notes.append("Vision: " + vision_result.get("note", "image does not match report"))
        elif vision_result and vision_result.get("status") == "match":
            evidence_verified = True
            vision_notes.append("Vision: photo matches reported issue")
        elif vision_result and vision_result.get("status") == "unclear":
            vision_notes.append("Vision: " + vision_result.get("note", "image unclear"))
        elif vision_result and vision_result.get("status") == "error":
            vision_notes.append("Vision: " + vision_result.get("note", "analysis failed"))

        if ai_gen_result and ai_gen_result.get("is_ai"):
            is_flagged = True
            vision_notes.append("AI-generated image suspected (heuristic score " + str(ai_gen_result.get("score")) + ")")

        if vision_notes:
            evidence_note = (evidence_note + "; " if evidence_note else "") + "; ".join(vision_notes)

    embedding_vec = compute_embedding(raw_text)
    embedding_str = ",".join(str(x) for x in embedding_vec.tolist())

    existing = db.query(Complaint).all()
    is_dup, parent_id, score = find_duplicate(embedding_vec, existing)

    tracking_id = make_tracking_id()
    complaint = Complaint(
        tracking_id=tracking_id,
        raw_text=raw_text,
        normalized_text=classification.get("normalized_text", ""),
        department=classification.get("department", ""),
        department_key=classification.get("department_key", "roads"),
        category=classification.get("category", "General"),
        priority=classification.get("priority", "Medium"),
        urgency_score=classification.get("urgency_score", 50),
        lat=lat,
        lon=lon,
        status="Pending",
        embedding=embedding_str,
        is_duplicate=is_dup,
        parent_cluster_id=parent_id if is_dup else None,
        photo_path=photo_path,
        photo_geotag_lat=photo_geo.get("geotag_lat"),
        photo_geotag_lon=photo_geo.get("geotag_lon"),
        photo_taken_at=photo_geo.get("taken_at"),
        evidence_verified=evidence_verified,
        evidence_note=evidence_note,
        source_ip=client_ip,
        flagged=is_flagged,
        flag_reason=flag_reason if is_flagged else None,
    )
    db.add(complaint)
    db.commit()
    db.refresh(complaint)

    return templates.TemplateResponse(request, "partials/submit_result.html", {
        "complaint": complaint,
        "is_duplicate": is_dup,
        "parent_id": parent_id,
        "action_recommended": classification.get("action_recommended", ""),
        "is_flagged": is_flagged,
        "flag_reason": flag_reason,
        "evidence_verified": evidence_verified,
        "evidence_note": evidence_note,
        "vision_result": vision_result,
        "ai_gen_result": ai_gen_result,
    })


@app.post("/api/complaints/analyze", response_class=JSONResponse)
def analyze_complaint(raw_text: str = Form(...)):
    """Lightweight classification endpoint for the 'Analyze' button.
    Returns the AI classification so the UI can decide (e.g. whether a
    photo is required for High/Critical) WITHOUT persisting anything."""
    classification = classify_complaint(raw_text)
    return {
        "normalized_text": classification.get("normalized_text", ""),
        "department": classification.get("department", ""),
        "department_key": classification.get("department_key", "roads"),
        "category": classification.get("category", "General"),
        "priority": classification.get("priority", "Medium"),
        "urgency_score": classification.get("urgency_score", 50),
        "action_recommended": classification.get("action_recommended", ""),
        "is_spam": bool(classification.get("is_spam")),
        "spam_reason": classification.get("spam_reason"),
        "requires_photo": classification.get("priority") in ("Critical", "High"),
    }


# ---------------- Auth ----------------

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {})


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user or user.password != password:
        return templates.TemplateResponse(request, "login.html", {"error": "Invalid credentials"})
    request.session[SESSION_KEY] = user.id
    if user.role == "admin":
        return RedirectResponse(url="/admin", status_code=303)
    return RedirectResponse(url=f"/dept/{user.department_key}", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)


# ---------------- Admin Dashboard ----------------

@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or user.role != "admin":
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request, "admin.html", {
        "departments": DEPARTMENTS,
        "user": user,
    })


@app.get("/dept/{key}", response_class=HTMLResponse)
def dept_dashboard(request: Request, key: str, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    if user.role != "admin" and user.department_key != key:
        return RedirectResponse(url="/login", status_code=303)
    dept = DEPARTMENT_MAP.get(key)
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    return templates.TemplateResponse(request, "dept.html", {
        "dept": dept,
        "user": user,
        "departments": DEPARTMENTS,
    })


# ---------------- Data APIs / Partials ----------------

def get_metrics(db: Session):
    complaints = db.query(Complaint).all()
    total = len(complaints)
    resolved = sum(1 for c in complaints if c.status == "Resolved")
    in_progress = sum(1 for c in complaints if c.status == "In Progress")
    resolved_pct = round((resolved / total * 100)) if total else 0
    dups = sum(1 for c in complaints if c.is_duplicate)
    dup_pct = round((dups / total * 100)) if total else 0
    critical = sum(1 for c in complaints if c.priority in ("Critical", "High"))
    return {
        "total": total,
        "resolved": resolved,
        "in_progress": in_progress,
        "resolved_pct": resolved_pct,
        "dup_pct": dup_pct,
        "critical": critical,
    }


def get_dept_breakdown(db: Session):
    from collections import Counter
    counts = Counter(c.department_key for c in db.query(Complaint).all() if c.department_key)
    return counts


@app.get("/api/dashboard/map-points")
def map_points(request: Request, db: Session = Depends(get_db)):
    complaints = _filter_complaints(db, request)
    return [_point_json(c) for c in complaints]


def _point_json(c: Complaint):
    return {
        "id": c.id,
        "tracking_id": c.tracking_id,
        "lat": c.lat,
        "lon": c.lon,
        "priority": c.priority,
        "department": c.department,
        "department_key": c.department_key,
        "category": c.category,
        "is_duplicate": c.is_duplicate,
        "status": c.status,
        "flagged": c.flagged,
        "photo": photo_url(c.photo_path),
        "evidence_verified": c.evidence_verified,
    }


def _filter_complaints(db: Session, request: Request):
    """Apply shared filter query params (dept, status, priority, category, flagged)."""
    dept = request.query_params.get("dept", "")
    status = request.query_params.get("status", "")
    priority = request.query_params.get("priority", "")
    category = request.query_params.get("category", "")
    flagged = request.query_params.get("flagged", "")
    dept_key = request.query_params.get("key", "")
    q = db.query(Complaint)
    if dept_key:
        q = q.filter(Complaint.department_key == dept_key)
    elif dept:
        q = q.filter(Complaint.department_key == dept)
    if status and status != "all":
        q = q.filter(Complaint.status == status)
    if priority and priority != "all":
        q = q.filter(Complaint.priority == priority)
    if category and category != "all":
        q = q.filter(Complaint.category == category)
    if flagged == "1":
        q = q.filter(Complaint.flagged.is_(True))
    elif flagged == "0":
        q = q.filter(Complaint.flagged.is_(False))
    return q.all()


@app.get("/api/dashboard/admin-map-points")
def admin_map_points(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or user.role != "admin":
        raise HTTPException(status_code=401)
    return [_point_json(c) for c in _filter_complaints(db, request)]


@app.get("/api/dashboard/dept-map-points")
def dept_map_points(request: Request, key: str, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401)
    if user.role != "admin" and user.department_key != key:
        raise HTTPException(status_code=403)
    points = _filter_complaints(db, request)
    return [_point_json(c) for c in points]


@app.get("/api/dashboard/categories")
def categories(db: Session = Depends(get_db)):
    from sqlalchemy import distinct
    rows = db.query(distinct(Complaint.category)).all()
    cats = sorted({r[0] for r in rows if r[0]})
    return {"categories": cats}


@app.get("/api/dashboard/stats-all")
def stats_all(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or user.role != "admin":
        raise HTTPException(status_code=401)
    tiles = []
    for d in DEPARTMENTS:
        cs = db.query(Complaint).filter(Complaint.department_key == d["key"]).all()
        pending_crit = sum(1 for c in cs if c.status != "Resolved" and c.priority == "Critical")
        tiles.append({
            "key": d["key"], "short": d["short"], "color": d["color"],
            "total": len(cs),
            "resolved": sum(1 for c in cs if c.status == "Resolved"),
            "pending_crit": pending_crit,
        })
    tiles.sort(key=lambda t: -t["total"])
    return templates.TemplateResponse(request, "partials/dept_tiles.html", {"tiles": tiles})


@app.get("/api/dashboard/admin-list")
def admin_list(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or user.role != "admin":
        raise HTTPException(status_code=401)
    dept = request.query_params.get("dept", "")
    status = request.query_params.get("status", "")
    priority = request.query_params.get("priority", "")
    category = request.query_params.get("category", "")
    flagged = request.query_params.get("flagged", "")
    q = db.query(Complaint)
    if dept:
        q = q.filter(Complaint.department_key == dept)
    if status and status != "all":
        q = q.filter(Complaint.status == status)
    if priority and priority != "all":
        q = q.filter(Complaint.priority == priority)
    if category and category != "all":
        q = q.filter(Complaint.category == category)
    if flagged == "1":
        q = q.filter(Complaint.flagged.is_(True))
    elif flagged == "0":
        q = q.filter(Complaint.flagged.is_(False))
    complaints = q.order_by(Complaint.created_at.desc()).all()
    return templates.TemplateResponse(request, "partials/complaint_list.html", {
        "complaints": complaints,
        "is_admin": True,
    })


@app.get("/api/dashboard/dept-filter")
def dept_filter_data(request: Request, key: str, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401)
    if user.role != "admin" and user.department_key != key:
        raise HTTPException(status_code=403)

    dept = DEPARTMENT_MAP.get(key)
    if not dept:
        raise HTTPException(status_code=404)

    status_filter = request.query_params.get("status", "all")
    priority_filter = request.query_params.get("priority", "all")
    category_filter = request.query_params.get("category", "all")

    q = db.query(Complaint).filter(Complaint.department_key == key)
    if status_filter not in ("", "all"):
        q = q.filter(Complaint.status == status_filter)
    if priority_filter not in ("", "all"):
        q = q.filter(Complaint.priority == priority_filter)
    if category_filter not in ("", "all"):
        q = q.filter(Complaint.category == category_filter)

    complaints = q.order_by(Complaint.created_at.desc()).all()
    return templates.TemplateResponse(request, "partials/complaint_list.html", {
        "complaints": complaints,
        "is_admin": user.role == "admin",
    })


@app.get("/api/dashboard/stats-dept")
def stats_dept(request: Request, key: str, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401)
    complaints = db.query(Complaint).filter(Complaint.department_key == key).all()
    total = len(complaints)
    resolved = sum(1 for c in complaints if c.status == "Resolved")
    pending = sum(1 for c in complaints if c.status == "Pending")
    in_progress = sum(1 for c in complaints if c.status == "In Progress")
    critical = sum(1 for c in complaints if c.priority == "Critical")
    high = sum(1 for c in complaints if c.priority == "High")
    return templates.TemplateResponse(request, "partials/dept_stats.html", {
        "total": total, "resolved": resolved, "pending": pending,
        "in_progress": in_progress, "critical": critical, "high": high,
    })


@app.get("/api/dashboard/chart-data")
def chart_data(db: Session = Depends(get_db)):
    from collections import Counter
    complaints = db.query(Complaint).all()
    dept_counts = Counter(c.department_key for c in complaints if c.department_key)
    priority_counts = Counter(c.priority for c in complaints)

    dept_labels = [DEPARTMENT_MAP[k]["short"] for k in dept_counts if k in DEPARTMENT_MAP]
    dept_values = [dept_counts[k] for k in dept_counts if k in DEPARTMENT_MAP]
    dept_colors = [DEPARTMENT_MAP[k]["color"] for k in dept_counts if k in DEPARTMENT_MAP]

    priority_order = ["Critical", "High", "Medium", "Low"]
    pri_labels = [p for p in priority_order if p in priority_counts]
    pri_values = [priority_counts[p] for p in priority_order if p in priority_counts]

    # Last 7 days trend
    today = datetime.date.today()
    days = []
    counts = []
    for i in range(6, -1, -1):
        d = today - datetime.timedelta(days=i)
        dc = sum(1 for c in complaints if c.created_at and c.created_at.date() == d)
        days.append(d.strftime("%d %b"))
        counts.append(dc)

    return {
        "dept_labels": dept_labels,
        "dept_values": dept_values,
        "dept_colors": dept_colors,
        "pri_labels": pri_labels,
        "pri_values": pri_values,
        "trend_labels": days,
        "trend_values": counts,
    }


@app.patch("/api/complaints/{complaint_id}/status")
def update_status(complaint_id: int, request: Request, status: str = Form(...), db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    if user.role != "admin" and complaint.department_key != user.department_key:
        raise HTTPException(status_code=403, detail="Not authorized for this complaint")

    if status not in ("Pending", "In Progress", "Resolved"):
        raise HTTPException(status_code=400, detail="Invalid status")

    complaint.status = status
    status_history = []
    if complaint.status_history:
        try:
            status_history = json.loads(complaint.status_history)
        except Exception:
            status_history = []
    status_history.append({
        "status": status,
        "by": user.name or user.username,
        "at": datetime.datetime.utcnow().strftime("%d %b %Y %H:%M"),
    })
    complaint.status_history = json.dumps(status_history)
    db.commit()
    db.refresh(complaint)

    return templates.TemplateResponse(request, "partials/complaint_card.html", {
        "complaint": complaint,
        "is_admin": user.role == "admin",
    })
