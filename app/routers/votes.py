from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import begin_write, get_db
from app.models import Report, Vote
from app.ratelimit import rate_limit
from app.security import require_csrf, voter_hash
from app.web import item_response, target_item

router = APIRouter(dependencies=[Depends(require_csrf)])


@router.post("/vote/{kind}/{id}", dependencies=[Depends(rate_limit("votes", 60, 3600))])
def vote(kind: str, id: int, request: Request, db: Session = Depends(get_db)):
    begin_write(db)
    item = target_item(db, kind, id, lock=True)
    identity = voter_hash(request)
    previous = db.scalar(select(Vote).where(Vote.target_type == kind,
        Vote.target_id == id, Vote.voter_hash == identity))
    if previous:
        db.delete(previous)
        item.vote_count -= 1
    else:
        db.add(Vote(target_type=kind, target_id=id, voter_hash=identity))
        item.vote_count += 1
    db.commit()
    return item_response(request, db, item, kind)


@router.post("/report/{kind}/{id}", dependencies=[Depends(rate_limit("reports", 30, 3600))])
def report(kind: str, id: int, request: Request, db: Session = Depends(get_db)):
    begin_write(db)
    item = target_item(db, kind, id, lock=True)
    identity = voter_hash(request)
    previous = db.scalar(select(Report.id).where(Report.target_type == kind,
        Report.target_id == id, Report.voter_hash == identity))
    if previous is None:
        db.add(Report(target_type=kind, target_id=id, voter_hash=identity))
        item.report_count += 1
        if item.report_count >= settings.report_threshold:
            item.is_hidden = True
            if kind == "answer":
                item.is_accepted = False
    db.commit()
    return item_response(request, db, item, kind, "Report received. Thank you.")
