import sys
from pathlib import Path

import bm25s
from pydantic import TypeAdapter

from .data_models import (
    MinimalSearchResults, MinimalSource, RagDataset, StudentSearchResults,
    UnansweredQuestion,
)
from .index import BM25_DIR, CHUNKS_FILE
from .tokenizer import tokenize


def search(
        question: UnansweredQuestion, k: int, processed_dir: str
) -> MinimalSearchResults:
    """Return the k best-scoring chunk locations for a question.

    Load the index saved by build_index under processed_dir, rank the
    chunks with BM25 and return their locations, highest score first. The
    question id and text are copied from question unchanged.
    """
    out = Path(processed_dir)
    if not (out / CHUNKS_FILE).is_file():
        raise FileNotFoundError(
            f"no index under {processed_dir}; run the index command first"
        )
    sources = TypeAdapter(list[MinimalSource]).validate_json(
        (out / CHUNKS_FILE).read_bytes()
    )
    bm25 = bm25s.BM25.load(str(out / BM25_DIR))
    # bm25s rejects a k larger than the number of chunks.
    ids, scores = bm25.retrieve(
        [tokenize(question.question)], k=min(k, len(sources)), sorted=True,
        show_progress=False
    )
    # A score of 0 means no query word is in the chunk; k is only a maximum.
    return MinimalSearchResults(
        question_id=question.question_id,
        question=question.question,
        retrieved_sources=[
            sources[i] for i, score in zip(ids[0], scores[0]) if score > 0
        ],
    )


def search_dataset(
        dataset_path: str, k: int, save_directory: str, processed_dir: str
) -> Path:
    """Search every question of a dataset and save the results.

    Write a StudentSearchResults JSON file named after the dataset file
    under save_directory, creating the directory if needed. Return the path
    of the written file.
    """
    dataset = RagDataset.model_validate_json(Path(dataset_path).read_bytes())
    results = StudentSearchResults(
        search_results=[
            search(q, k, processed_dir) for q in dataset.rag_questions
        ],
        k=k,
    )
    out = Path(save_directory)
    out.mkdir(parents=True, exist_ok=True)
    path = out / Path(dataset_path).name
    try:
        path.write_text(results.model_dump_json(indent=2), encoding="utf-8")
    except BaseException:
        print(f"Warning: saving failed; {path} may be incomplete.",
              file=sys.stderr)
        raise
    return path
