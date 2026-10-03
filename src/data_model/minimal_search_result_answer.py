"""The MinimalSearchResults and MinimalAnswer models
represent the search results and an answer."""
from pydantic import BaseModel
from typing import List
from minimal_source import MinimalSource


class MinimalSearchResults(BaseModel):
    question_id: str
    question: str
    retrieved_sources: List[MinimalSource]


class MinimalAnswer(MinimalSearchResults):
    answer: str
