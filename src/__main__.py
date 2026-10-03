import sys
# from pathlib import Path
from fire.core import FireError, FireExit
import fire


class Orchestrator:
    """
    CLI built with Python Fire.
    Every command:
        uv run python -m src <command> [options]
    """

    def __init__(self):
        pass

    def index(
            self, max_chunk_size: int = 2000
    ):
        """Ingest data/raw/ and build the index under data/processed/."""

    def search(
            self, query: str, k: int
    ):
        """Return the top-k sources for a single query."""

    def search_dataset(
            self, dataset_path: str, k: int, save_directory: str
    ):
        """
        Run search over a whole dataset and
        write a StudentSearchResults JSON file.
        """

    def answer(
            self, query: str, k: int
    ):
        """Answer a single query using the retrieved context."""

    def answer_dataset(
            self, stuent_search_results_path: str, save_directory: str
    ):
        """
        Generate answers for a dataset,
        producing a StudentSearchResultsAndAnswer JSON file.
        """

    def evaluate(
            self, student_search_results_path: str, dataset_path: str
    ):
        """
        Report your own recall@k against a ground-truth dataset,
        for your own testing.
        """


if __name__ == "__main__":
    try:
        fire.Fire(Orchestrator)
    except (FireError, FireExit) as e:
        print(f"Error while running Fire: {e}", file=sys.stderr)
        sys.exit(1)
