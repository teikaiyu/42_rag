from pathlib import Path

from .data_models import (
    AnsweredQuestion, MinimalSource, RagDataset, StudentSearchResults,
)

KS: tuple[int, ...] = (1, 3, 5, 10)
MIN_IOU = 0.05


def iou(a: MinimalSource, b: MinimalSource) -> float:
    """Return the intersection over union of two spans in the same file.

    Spans are [first, last) and spans in different files never overlap.
    """
    if a.file_path != b.file_path:
        return 0.0
    inter = max(0, min(a.last_character_index, b.last_character_index)
                - max(a.first_character_index, b.first_character_index))
    union = (a.last_character_index - a.first_character_index
             + b.last_character_index - b.first_character_index - inter)
    return inter / union if union > 0 else 0.0


def evaluate(
        student_search_results_path: str, dataset_path: str
) -> tuple[int, int, dict[int, float]]:
    """Return recall@k for each k in KS against a ground-truth dataset.

    For each question, recall@k is the share of its correct sources that
    overlap one of the top-k retrieved sources with an IoU of at least
    MIN_IOU. Questions are matched by question_id and recall is averaged
    over the answered questions of the dataset; a question with no search
    result counts as 0.

    Return the number of answered questions that have a search result, the
    number of answered questions, and the recall for each k.
    """
    results = StudentSearchResults.model_validate_json(
        Path(student_search_results_path).read_bytes()
    )
    dataset = RagDataset.model_validate_json(Path(dataset_path).read_bytes())
    retrieved = {r.question_id: r.retrieved_sources
                 for r in results.search_results}
    answered = [q for q in dataset.rag_questions
                if isinstance(q, AnsweredQuestion) and q.sources]
    recalls: dict[int, float] = {}
    for k in KS:
        total = 0.0
        for q in answered:
            top_k = retrieved.get(q.question_id, [])[:k]
            found = sum(
                any(iou(s, r) >= MIN_IOU for r in top_k) for s in q.sources
            )
            total += found / len(q.sources)
        recalls[k] = total / len(answered) if answered else 0.0
    matched = sum(q.question_id in retrieved for q in answered)
    return matched, len(answered), recalls
