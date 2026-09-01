from sqlalchemy.orm import Session
from app.database import Complaint, User
from app.ai_service import compute_embedding, keyword_classify
from app.departments import DEPARTMENT_MAP, DEPARTMENTS
import uuid


def make_tracking():
    return "SAM-" + uuid.uuid4().hex[:8].upper()


def _classify(raw_text):
    data = keyword_classify(raw_text)
    dept = DEPARTMENT_MAP[data["department_key"]]
    return {
        "normalized_text": raw_text,
        "department": dept["name"],
        "department_key": dept["key"],
        "category": data["category"],
        "priority": "Medium",
        "urgency_score": 50,
        "status": "Pending",
    }


def _row(raw_text, lat, lon, **overrides):
    base = _classify(raw_text)
    base.update(overrides)
    base["raw_text"] = raw_text
    base["lat"] = lat
    base["lon"] = lon
    return base


SEED_COMPLAINTS = [
    _row("MG Road ke beech mein bada sa pothole hai, bikes wale gir rahe hain daily", 28.6139, 77.2090, priority="High", urgency_score=78),
    _row("Humare colony mein paani 3 din se nahi aa raha, bahut pareshani ho rahi hai", 28.6229, 77.2150, priority="Critical", urgency_score=92, status="In Progress"),
    _row("Kachra nahi uthaya ja raha hai ek hafte se, bahut badbu aa rahi hai", 28.6300, 77.2180, priority="High", urgency_score=81),
    _row("Industrial area mein baar baar light ja rahi hai, factories band ho rahi hain", 28.6450, 77.2300, priority="High", urgency_score=75),
    _row("Gas leak ho gaya hai petrol pump pe, jaldi fire brigade bhejo", 28.6400, 77.2110, priority="Critical", urgency_score=96),
    _row("Market mein do log lad rahe hain, maar peet ho gayi, police bulao", 28.6350, 77.2200, priority="Critical", urgency_score=88, category="Fight"),
    _row("Mera mobile chori ho gaya hai bus mein, police report karni hai", 28.6280, 77.2250, priority="Medium", urgency_score=60, category="Theft"),
    _row("Aaj subah ek aadmi ka murder ho gaya gali ke paas", 28.6320, 77.2170, priority="Critical", urgency_score=99, category="Murder"),
    _row("School ke paas khuli naali hai bachon ke liye khatarnak", 28.6180, 77.2250, priority="High", urgency_score=85, category="Open drain"),
    _row("Natural park mein koi illegal construction kar raha hai", 28.6330, 77.2230, priority="High", urgency_score=72, category="Illegal construction", department_key="planning"),
    _row("Forest fire lag gaya hai paas ke area mein", 28.6550, 77.2400, priority="Critical", urgency_score=98, category="Forest fire", department_key="fire"),
    _row("Mai bahut bhukha aur beghar hoon, money chori ho gayi", 28.6260, 77.2190, priority="High", urgency_score=75, category="Homeless", department_key="social"),
    _row("Market area mein aawara dogs ke jhund ghoom rahe hain logon ko kaat rahe hain", 28.6410, 77.2140, priority="Medium", urgency_score=62, category="Stray animals", department_key="environment"),
    _row("Bus service band hai sham ke baad logon ko dikkat ho rahi hai", 28.6380, 77.2220, priority="Medium", urgency_score=55, category="Public transport", department_key="transport"),
    _row("Government school mein roofs tap rahi hain bachon ke liye khatarnak", 28.6200, 77.2160, priority="High", urgency_score=74, category="School infrastructure", department_key="education"),
]


def seed_database(db: Session):
    existing = db.query(Complaint).filter(Complaint.tracking_id.isnot(None)).count()
    if existing > 0:
        return

    for data in SEED_COMPLAINTS:
        embedding_vec = compute_embedding(data["raw_text"])
        embedding_str = ",".join(str(x) for x in embedding_vec.tolist())

        complaint = Complaint(
            tracking_id=make_tracking(),
            raw_text=data["raw_text"],
            normalized_text=data["normalized_text"],
            department=data["department"],
            department_key=data["department_key"],
            category=data["category"],
            priority=data["priority"],
            urgency_score=data["urgency_score"],
            lat=data["lat"],
            lon=data["lon"],
            status=data["status"],
            embedding=embedding_str,
            is_duplicate=False,
            parent_cluster_id=None,
        )
        db.add(complaint)

    db.commit()


def seed_users(db: Session):
    if db.query(User).count() > 0:
        return

    admin = User(
        username="admin",
        password="admin123",
        name="System Administrator",
        role="admin",
        department_key=None,
        department_name=None,
    )
    db.add(admin)

    for d in DEPARTMENTS:
        user = User(
            username=d["key"],
            password=d["password"],
            name=f"{d['officer']} - {d['short']}",
            role="officer",
            department_key=d["key"],
            department_name=d["name"],
        )
        db.add(user)

    db.commit()
