from pydantic import BaseModel, Field, model_validator
import uuid
from typing import List


class MinimalSource(BaseModel):
    """Location of a text span in a corpus file."""
    file_path: str
    first_character_index: int = Field(ge=0)
    last_character_index: int = Field(ge=0)

    @model_validator(mode="after")
    def check_order(self) -> "MinimalSource":
        """Reject a span that ends before it starts."""
        if self.first_character_index > self.last_character_index:
            raise ValueError(
                "first_character_index is after last_character_index"
            )
        return self


class UnansweredQuestion(BaseModel):
    """Question to be answered by the RAG system."""
    question_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    question: str


class AnsweredQuestion(UnansweredQuestion):
    """Question with its ground-truth sources and reference answer."""
    sources: List[MinimalSource]
    answer: str


class RagDataset(BaseModel):
    """Container for a question dataset file."""
    rag_questions: List[AnsweredQuestion | UnansweredQuestion]


class MinimalSearchResults(BaseModel):
    """Retrieved sources for a single question."""
    question_id: str
    question: str
    retrieved_sources: List[MinimalSource]


class MinimalAnswer(MinimalSearchResults):
    """Retrieved sources and generated answer for a single question."""
    answer: str


class StudentSearchResults(BaseModel):
    """Retrieval results for a whole dataset."""
    search_results: List[MinimalSearchResults]
    k: int


class StudentSearchResultsAndAnswer(BaseModel):
    """Retrieval results with generated answers for a whole dataset."""
    search_results: List[MinimalAnswer]
    k: int
