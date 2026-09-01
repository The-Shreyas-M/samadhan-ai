from fastapi import Request, HTTPException, Depends
from sqlalchemy.orm import Session
from app.database import User, get_db

SESSION_KEY = "samadhan_user_id"


def get_current_user(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get(SESSION_KEY)
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id).first()


def require_auth(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_admin(request: Request, db: Session = Depends(get_db)):
    user = require_auth(request, db)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user
