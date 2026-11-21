from pydantic import BaseModel, Field, field_validator

from app.config import settings
from app.filters import clean_text


class QuestionInput(BaseModel):
    text: str = Field(min_length=10, max_length=1000)
    category: str

    @field_validator("text", mode="before")
    @classmethod
    def text_check(cls, value):
        return clean_text(value)

    @field_validator("category")
    @classmethod
    def category_check(cls, value):
        if value not in settings.categories:
            raise ValueError("Choose a valid category.")
        return value


class AnswerInput(BaseModel):
    text: str = Field(min_length=2, max_length=2000)

    @field_validator("text", mode="before")
    @classmethod
    def text_check(cls, value):
        return clean_text(value)
