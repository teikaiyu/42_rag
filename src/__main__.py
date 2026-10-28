import sys
# from pathlib import Path
# from fire.core import FireError, FireExit
import fire

from .data_models import UnansweredQuestion
from .index import build_index
from .search import search, search_dataset
from .answer import SmallLLMModel, answer, answer_dataset
from .evaluate import evaluate


class Orchestrator:
    """
    CLI built with Python Fire.
    Every command:
        uv run python -m src <command> [options]
    """

    def index(
            self, max_chunk_size: int = 2000, raw_dir: str = "data/raw",
            processed_dir: str = "data/processed"
    ) -> None:
        """Ingest data/raw/ and build the index under data/processed/."""
        count = build_index(raw_dir, processed_dir, max_chunk_size)
        print(f"Ingestion complete! {count} chunks saved under "
              f"{processed_dir}/")

    def search(
            self, query: str, k: int, processed_dir: str = "data/processed"
    ) -> None:
        """Print the top-k sources for a single query, one per line."""
        # Fire passes a numeric-only query as int.
        question = UnansweredQuestion(question=str(query))
        for s in search(question, k, processed_dir).retrieved_sources:
            print(f"{s.file_path} "
                  f"[{s.first_character_index}:{s.last_character_index}]")

    def search_dataset(
            self, dataset_path: str, k: int, save_directory: str,
            processed_dir: str = "data/processed"
    ) -> None:
        """Search a whole dataset and write a StudentSearchResults file."""
        path = search_dataset(dataset_path, k, save_directory, processed_dir)
        print(f"Saved student_search_results to {path}")

    def answer(
            self, query: str, k: int, processed_dir: str = "data/processed",
            show_retrieved_sources: bool = False
    ) -> None:
        """Print the answer to a single query.

        With show_retrieved_sources, also print the sources it was based on.
        """
        # Fire passes a numeric-only query as int.
        question = UnansweredQuestion(question=str(query))
        res = answer(search(question, k, processed_dir), llm=SmallLLMModel())
        print()
        print(res.answer)
        if show_retrieved_sources:
            print()
            for s in res.retrieved_sources:
                print(f"{s.file_path} "
                      f"[{s.first_character_index}:{s.last_character_index}]")

    def answer_dataset(
            self, student_search_results_path: str, save_directory: str
    ) -> None:
        """Answer every question of a search results file.

        Write a StudentSearchResultsAndAnswer file under save_directory.
        """
        path = answer_dataset(student_search_results_path, save_directory)
        print(f"Saved student_search_results_and_answer to {path}")

    def evaluate(
            self, student_search_results_path: str, dataset_path: str
    ) -> None:
        """Print recall@k of search results against a ground-truth dataset."""
        matched, total, recalls = evaluate(
            student_search_results_path, dataset_path
        )
        print(f"Matched {matched} of {total} questions")
        if matched == 0:
            print("Warning: no question_id matched. Check that both files "
                  "come from the same dataset and that dataset_path is an "
                  "AnsweredQuestions file.", file=sys.stderr)
        print(" ".join(f"Recall@{k}: {r:.3f}" for k, r in recalls.items()))


if __name__ == "__main__":
    fire.Fire(Orchestrator)
