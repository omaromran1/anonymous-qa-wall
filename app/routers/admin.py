import hmac

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import begin_write, get_db
from app.models import Answer, Question, Report, Vote
from app.ratelimit import rate_limit
from app.security import admin_signer, cookie_options, is_admin, require_admin, require_csrf, token_hash
from app.web import redirect, render

router = APIRouter()


@router.get("/admin")
def admin_page(request: Request, db: Session = Depends(get_db)):
    if not is_admin(request):
        return render(request, "login.html")
    questions = db.scalars(select(Question).where(or_(Question.report_count > 0,
        Question.is_hidden.is_(True))).order_by(Question.created_at.desc()).limit(100)).all()
    answers = db.scalars(select(Answer).where(or_(Answer.report_count > 0,
        Answer.is_hidden.is_(True))).order_by(Answer.created_at.desc()).limit(100)).all()
    return render(request, "admin.html", questions=questions, answers=answers)


@router.post("/admin", dependencies=[Depends(require_csrf), Depends(rate_limit("admin_login", 5, 60))])
def admin_login(request: Request):
    form = request.state.form
    token = form.get("token", "")
    if not settings.admin_token or not isinstance(token, str) or not hmac.compare_digest(token.encode(), settings.admin_token.encode()):
        raise HTTPException(403, "Invalid admin token.")
    response = redirect("/admin")
    response.set_cookie("admin", admin_signer.dumps(token_hash(settings.admin_token)), max_age=3600, **cookie_options())
    return response


@router.post("/admin/logout", dependencies=[Depends(require_csrf)])
def logout():
    response = redirect("/admin")
    response.delete_cookie("admin", path="/")
    return response


def locked_item(db, kind, id):
    if kind not in {"question", "answer"}:
        raise HTTPException(404, "Unknown item type.")
    if kind == "answer":
        answer = db.get(Answer, id)
        if not answer:
            raise HTTPException(404, "Item not found.")
        db.scalar(select(Question).where(Question.id == answer.question_id).with_for_update())
    model = Question if kind == "question" else Answer
    item = db.scalar(select(model).where(model.id == id).with_for_update().execution_options(populate_existing=True))
    if not item:
        raise HTTPException(404, "Item not found.")
    return item


def clear_records(db, model, kind, ids):
    db.execute(delete(model).where(model.target_type == kind, model.target_id.in_(ids)))


@router.post("/admin/{kind}/{id}/unhide", dependencies=[Depends(require_csrf), Depends(require_admin)])
def unhide(kind: str, id: int, request: Request, db: Session = Depends(get_db)):
    begin_write(db)
    item = locked_item(db, kind, id)
    item.is_hidden = False
    item.report_count = 0
    clear_records(db, Report, kind, [id])
    db.commit()
    return redirect("/admin")


@router.post("/admin/{kind}/{id}/delete", dependencies=[Depends(require_csrf), Depends(require_admin)])
def delete_item(kind: str, id: int, request: Request, db: Session = Depends(get_db)):
    begin_write(db)
    item = locked_item(db, kind, id)
    if kind == "question":
        answer_ids = list(db.scalars(select(Answer.id).where(Answer.question_id == id)))
        for model in (Vote, Report):
            clear_records(db, model, "answer", answer_ids)
    for model in (Vote, Report):
        clear_records(db, model, kind, [id])
    db.delete(item)
    db.commit()
    return redirect("/admin")
