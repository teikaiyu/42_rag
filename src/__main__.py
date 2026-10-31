import sys

import fire
from pydantic import ValidationError

from .answer import SmallLLMModel, answer, answer_dataset
from .data_models import UnansweredQuestion
from .evaluate import evaluate
from .index import build_index
from .search import search, search_dataset

MAX_CHUNK_SIZE = 2000


def positive_int(name: str, value: object, maximum: int | None = None) -> int:
    """Return value if it is a positive int (at most maximum), else raise.

    Fire does not convert by type hints: "abc" arrives as a str and True
    would pass as an int, so check the actual type.
    """
    if (isinstance(value, bool) or not isinstance(value, int) or value < 1
            or (maximum is not None and value > maximum)):
        limit = f" up to {maximum}" if maximum is not None else ""
        raise ValueError(
            f"--{name} must be a positive integer{limit}, got {value!r}"
        )
    return value


def question_of(query: object) -> UnansweredQuestion:
    """Return the query as a question, or raise if it is blank."""
    # Fire passes a numeric-only query as int.
    text = str(query)
    if not text.strip():
        raise ValueError("the query must not be empty")
    return UnansweredQuestion(question=text)


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
        max_chunk_size = positive_int(
            "max_chunk_size", max_chunk_size, MAX_CHUNK_SIZE
        )
        count = build_index(raw_dir, processed_dir, max_chunk_size)
        print(f"Ingestion complete! {count} chunks saved under "
              f"{processed_dir}/")

    def search(
            self, query: str, k: int, processed_dir: str = "data/processed"
    ) -> None:
        """Print the top-k sources for a single query, one per line."""
        question = question_of(query)
        k = positive_int("k", k)
        sources = search(question, k, processed_dir).retrieved_sources
        if not sources:
            print("No source contains a word of the query.", file=sys.stderr)
        for s in sources:
            print(f"{s.file_path} "
                  f"[{s.first_character_index}:{s.last_character_index}]")

    def search_dataset(
            self, dataset_path: str, k: int, save_directory: str,
            processed_dir: str = "data/processed"
    ) -> None:
        """Search a whole dataset and write a StudentSearchResults file."""
        k = positive_int("k", k)
        path = search_dataset(dataset_path, k, save_directory, processed_dir)
        print(f"Saved student_search_results to {path}")

    def answer(
            self, query: str, k: int, processed_dir: str = "data/processed",
            show_retrieved_sources: bool = False
    ) -> None:
        """Print the answer to a single query.

        With show_retrieved_sources, also print the sources it was based on.
        """
        question = question_of(query)
        k = positive_int("k", k)
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


def main() -> None:
    """Run the CLI; report errors in one line instead of a traceback."""
    try:
        fire.Fire(Orchestrator)
    except KeyboardInterrupt:
        sys.exit(130)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        print(f"Error: invalid {e.title} data"
              f"{f' at {where}' if where else ''}: {first['msg']}",
              file=sys.stderr)
        sys.exit(1)
    # FireExit (after --help or a usage error) is a SystemExit, not caught.
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
