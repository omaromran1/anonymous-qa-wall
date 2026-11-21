from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.config import settings
from app.filters import relative_time
from app.models import Answer, Question, Vote
from app.security import owns, voter_hash

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["relative"] = relative_time


def render(request, name, **context):
    return templates.TemplateResponse(request=request, name=name, context={
        "settings": settings, "csrf": request.state.csrf, **context,
    })


def redirect(path):
    return RedirectResponse(path, status_code=303)


def get_question(db, id, lock=False):
    statement = select(Question).where(Question.id == id)
    question = db.scalar(statement.with_for_update() if lock else statement)
    if not question or question.is_hidden:
        raise HTTPException(404, "Question not found or hidden.")
    return question


def target_item(db, kind, id, lock=False):
    if kind not in {"question", "answer"}:
        raise HTTPException(404, "Unknown item type.")
    if kind == "question":
        return get_question(db, id, lock)
    # Lock parent first everywhere to avoid accept/delete deadlocks.
    answer = db.get(Answer, id)
    if not answer:
        raise HTTPException(404, "Answer not found.")
    get_question(db, answer.question_id, lock)
    statement = select(Answer).where(Answer.id == id).execution_options(populate_existing=True)
    answer = db.scalar(statement.with_for_update() if lock else statement)
    if not answer or answer.is_hidden:
        raise HTTPException(404, "Answer not found or hidden.")
    return answer


def item_context(request, db, item, kind):
    question = item if kind == "question" else db.get(Question, item.question_id)
    voted = db.scalar(select(Vote.id).where(Vote.target_type == kind,
        Vote.target_id == item.id, Vote.voter_hash == voter_hash(request))) is not None
    return dict(item=item, kind=kind, question=question, owner=owns(request, question), voted=voted)


def item_response(request, db, item, kind, message=""):
    if request.headers.get("hx-request") == "true":
        return render(request, "item.html", message=message, **item_context(request, db, item, kind))
    question_id = item.id if kind == "question" else item.question_id
    return redirect(f"/questions/{question_id}" if not item.is_hidden else "/")
