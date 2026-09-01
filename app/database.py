from sqlalchemy import create_engine, Column, Integer, String, Text, Float, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

DATABASE_URL = "sqlite:///./samadhan.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False)
    password = Column(String(128), nullable=False)
    name = Column(String(128))
    role = Column(String(32), default="officer")  # 'admin' | 'officer'
    department_key = Column(String(64), nullable=True)  # None for admin
    department_name = Column(String(128), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Complaint(Base):
    __tablename__ = "complaints"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tracking_id = Column(String(24), unique=True, index=True)
    raw_text = Column(Text, nullable=False)
    normalized_text = Column(Text)
    department = Column(String(128))
    department_key = Column(String(64))
    category = Column(String(64))
    priority = Column(String(16))
    urgency_score = Column(Integer)
    is_duplicate = Column(Boolean, default=False)
    parent_cluster_id = Column(Integer, nullable=True)
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    status = Column(String(32), default="Pending")
    status_history = Column(Text, default="")
    embedding = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Evidence & integrity
    photo_path = Column(String(255))
    photo_geotag_lat = Column(Float, nullable=True)
    photo_geotag_lon = Column(Float, nullable=True)
    photo_taken_at = Column(String(64))
    evidence_verified = Column(Boolean, default=False)
    evidence_note = Column(Text)
    source_ip = Column(String(64))

    # Spam / suspicious
    flagged = Column(Boolean, default=False)
    flag_reason = Column(String(255))

    scheduled_timestamp = Column(DateTime, default=datetime.utcnow)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
