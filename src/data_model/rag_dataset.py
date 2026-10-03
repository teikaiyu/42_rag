"""The RagDataset model represents a dataset of RAG questions."""
from pydantic import BaseModel
from typing import List
from un_answered_question import AnsweredQuestion, UnansweredQuestion


class RagDataset(BaseModel):
    rag_questions: List[AnsweredQuestion | UnansweredQuestion]
