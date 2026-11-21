from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.database import begin_write, get_db
from app.models import Answer
from app.ratelimit import rate_limit
from app.schemas import AnswerInput
from app.security import owns, require_csrf
from app.web import get_question, item_context, redirect, render, target_item

router = APIRouter(dependencies=[Depends(require_csrf)])


@router.post("/questions/{id}/answers", dependencies=[Depends(rate_limit("answers", 20, 3600))])
def create_answer(id: int, request: Request, db: Session = Depends(get_db)):
    form = request.state.form
    data = AnswerInput(text=form.get("text", ""))
    begin_write(db)
    question = get_question(db, id, lock=True)
    db.add(Answer(question_id=id, text=data.text))
    db.commit()
    if request.headers.get("hx-request") == "true":
        answers = db.scalars(select(Answer).where(Answer.question_id == id,
            Answer.is_hidden.is_(False)).order_by(Answer.is_accepted.desc(),
            Answer.vote_count.desc(), Answer.created_at, Answer.id))
        return render(request, "answers.html", question=question,
            answers=[item_context(request, db, a, "answer") for a in answers], message="Answer posted.")
    return redirect(f"/questions/{id}#answers-section")


@router.post("/answers/{id}/accept", dependencies=[Depends(rate_limit("acceptance", 60, 3600))])
def accept_answer(id: int, request: Request, db: Session = Depends(get_db)):
    begin_write(db)
    answer = target_item(db, "answer", id, lock=True)
    question = get_question(db, answer.question_id)
    if not owns(request, question):
        raise HTTPException(403, "Only the asker in the original browser can accept an answer.")
    accepted = not answer.is_accepted
    db.execute(update(Answer).where(Answer.question_id == question.id).values(is_accepted=False))
    answer.is_accepted = accepted
    db.commit()
    return redirect(f"/questions/{question.id}#answers-section")
