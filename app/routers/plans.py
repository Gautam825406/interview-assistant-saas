"""Public plans + health."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Plan
from ..settings_util import plan_dict

router = APIRouter(tags=["public"])


@router.get("/api/health")
def health():
    return {"status": "ok"}


@router.get("/api/plans")
def list_plans(db: Session = Depends(get_db)):
    plans = (
        db.query(Plan)
        .filter(Plan.active.is_(True))
        .order_by(Plan.sort_order, Plan.id)
        .all()
    )
    return [plan_dict(p) for p in plans]
