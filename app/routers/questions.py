import math
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Answer, Question
from app.ratelimit import rate_limit
from app.schemas import QuestionInput
from app.security import cookie_options, require_csrf, token_hash
from app.web import get_question, item_context, redirect, render

router = APIRouter()


@router.get("/")
def index(request: Request, sort: str = "newest", category: str = "",
          page: int = Query(1, ge=1, le=1000000), db: Session = Depends(get_db)):
    if sort not in {"newest", "votes", "unanswered"}:
        raise HTTPException(400, "Choose a valid sort order.")
    if category and category not in settings.categories:
        raise HTTPException(400, "Choose a valid category.")
    query = select(Question).where(Question.is_hidden.is_(False))
    if category:
        query = query.where(Question.category == category)
    if sort == "unanswered":
        query = query.where(~exists().where(Answer.question_id == Question.id,
                                            Answer.is_hidden.is_(False)))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    query = query.order_by(Question.vote_count.desc(), Question.created_at.desc(), Question.id.desc()) if sort == "votes" else query.order_by(Question.created_at.desc(), Question.id.desc())
    items = [item_context(request, db, q, "question") for q in db.scalars(query.offset((page - 1) * 20).limit(20))]
    return render(request, "index.html", items=items, sort=sort, category=category,
                  page=page, pages=max(1, math.ceil(total / 20)), total=total)


@router.post("/questions", dependencies=[Depends(require_csrf), Depends(rate_limit("questions", 5, 3600))])
def create_question(request: Request, db: Session = Depends(get_db)):
    form = request.state.form
    data = QuestionInput(text=form.get("text", ""), category=form.get("category", ""))
    raw = secrets.token_urlsafe(32)
    question = Question(**data.model_dump(), edit_token_hash=token_hash(raw))
    db.add(question)
    db.commit()
    response = redirect(f"/questions/{question.id}")
    response.set_cookie(f"owner_{question.id}", raw, max_age=31536000, **cookie_options())
    return response


@router.get("/questions/{id}")
def detail(id: int, request: Request, db: Session = Depends(get_db)):
    question = get_question(db, id)
    answers = db.scalars(select(Answer).where(Answer.question_id == id,
        Answer.is_hidden.is_(False)).order_by(Answer.is_accepted.desc(),
        Answer.vote_count.desc(), Answer.created_at, Answer.id))
    return render(request, "detail.html", question_context=item_context(request, db, question, "question"),
                  question=question, answers=[item_context(request, db, a, "answer") for a in answers])
