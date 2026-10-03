"""The StudentSearchResults and Student SearchResultsAndAnswer
models represent search results and search results with answers."""
from pydantic import BaseModel
from typing import List
from minimal_search_result_answer import MinimalSearchResults, MinimalAnswer


class StudentSearchResults(BaseModel):
    search_results: List[MinimalSearchResults]
    k: int


class StudentSearchResultsAndAnswer(BaseModel):
    search_results: List[MinimalAnswer]
    k: int
