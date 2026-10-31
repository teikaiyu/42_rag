*This project has been created as part of the 42 curriculum by heychong.*

# RAG against the machine

## Description

A Retrieval-Augmented Generation (RAG) system that answers questions about the
[vLLM](https://github.com/vllm-project/vllm) 0.10.1 repository.

The goal is to find, for a natural-language question, the places in the
repository (documentation and Python code) that hold the answer, and to let a
small language model (Qwen/Qwen3-0.6B) answer from those places only.

The system has four steps:

1. **index**: split every target file of the corpus into chunks of at most
   2000 characters and build a BM25 index over them.
2. **search** / **search_dataset**: rank the chunks for one question or for a
   whole dataset of questions, and return their locations
   (`file_path`, first and last character index).
3. **evaluate**: compute recall@k of the search results against a
   ground-truth dataset, for our own iteration.
4. **answer** / **answer_dataset**: give the retrieved text to Qwen3-0.6B
   and generate an answer grounded in it.

## Instructions

### Requirements

- [uv](https://docs.astral.sh/uv/) and Python 3.10 or later.
- Several GB of free disk space (PyTorch and the model weights).
- Network access on the first `answer` run, to download Qwen/Qwen3-0.6B from
  Hugging Face.

### Installation

```bash
make install        # = uv sync
```

On Linux, PyTorch is taken from PyTorch's CPU-only index (see
[Design decisions](#design-decisions)).

### Data layout

The corpus and datasets are not part of the repository. Place them as follows:

```
data/raw/vllm-0.10.1/...                     # the provided vLLM repository
data/datasets/UnansweredQuestions/*.json     # questions
data/datasets/AnsweredQuestions/*.json       # questions with their gold sources
```

Generated files go to `data/processed/` (the index) and `data/output/`
(search results and answers). Every input and output path is a CLI argument.

### Makefile

| Rule | What it does |
|---|---|
| `make install` | `uv sync` |
| `make run ARGS="..."` | `uv run python -m src ...` |
| `make debug ARGS="..."` | the same, under `pdb` |
| `make clean` | remove `__pycache__`, `.mypy_cache`, `.pytest_cache`, `data/processed`, `data/output` |
| `make fclean` | `clean`, then remove `.venv` |
| `make lint` | `flake8 .` and `mypy .` with the flags of the subject |
| `make lint-strict` | `flake8 .` and `mypy . --strict` (optional) |

### Commands

All commands run as `uv run python -m src <command> [options]`, and
`--help` shows the options of each.

| Command | Options (default) |
|---|---|
| `index` | `--max_chunk_size` (2000, at most 2000), `--raw_dir` (`data/raw`), `--processed_dir` (`data/processed`) |
| `search QUERY` | `--k` (required), `--processed_dir` |
| `search_dataset` | `--dataset_path`, `--k`, `--save_directory`, `--processed_dir` |
| `answer QUERY` | `--k` (required), `--processed_dir`, `--show_retrieved_sources` (False) |
| `answer_dataset` | `--student_search_results_path`, `--save_directory` |
| `evaluate` | `--student_search_results_path`, `--dataset_path` |

## Example usage

```bash
# 1. Index the corpus once
uv run python -m src index --max_chunk_size 2000
# Ingestion complete! 14638 chunks saved under data/processed/

# 2. One question
uv run python -m src search "How do I enable LoRA adapters?" --k 3
# data/raw/vllm-0.10.1/docs/features/lora.md [0:1874]
# data/raw/vllm-0.10.1/docs/features/lora.md [4075:4693]
# data/raw/vllm-0.10.1/docs/features/lora.md [14472:15147]

uv run python -m src answer "How do I enable LoRA adapters?" --k 3 --show_retrieved_sources True

# 3. A whole dataset (scope --save_directory by dataset)
uv run python -m src search_dataset \
    --dataset_path data/datasets/UnansweredQuestions/dataset_docs_public.json \
    --k 10 \
    --save_directory data/output/search_results/UnansweredQuestions
# Saved student_search_results to data/output/search_results/UnansweredQuestions/dataset_docs_public.json

# 4. Our own recall@k (the official score comes from the moulinette)
uv run python -m src evaluate \
    --student_search_results_path data/output/search_results/UnansweredQuestions/dataset_docs_public.json \
    --dataset_path data/datasets/AnsweredQuestions/dataset_docs_public.json
# Matched 100 of 100 questions
# Recall@1: 0.600 Recall@3: 0.800 Recall@5: 0.870 Recall@10: 0.870

# 5. Answers for the search results
uv run python -m src answer_dataset \
    --student_search_results_path data/output/search_results/UnansweredQuestions/dataset_docs_public.json \
    --save_directory data/output/search_results_and_answer/UnansweredQuestions
```

## System architecture

```
data/raw/vllm-0.10.1/**  --index-->  data/processed/chunks.json   (chunk locations)
                                     data/processed/bm25/         (BM25 index)

question(s) --search / search_dataset-->  top-k locations  (StudentSearchResults)
StudentSearchResults --evaluate (+ AnsweredQuestions)-->  recall@1/3/5/10
StudentSearchResults --answer_dataset--> text of each location --> Qwen3-0.6B
                                     --> StudentSearchResultsAndAnswer
```

| File | Role |
|---|---|
| `src/__main__.py` | the Fire CLI (`Orchestrator`), input checks, one-line error messages |
| `src/data_models.py` | the pydantic models of the subject |
| `src/index.py` | file collection, chunking, saving the chunks and the BM25 index |
| `src/tokenizer.py` | the tokenizer shared by indexing and search |
| `src/search.py` | BM25 retrieval for one question or a dataset |
| `src/evaluate.py` | recall@k with the file + IoU matching rule |
| `src/answer.py` | reading the retrieved text back and generating with Qwen3-0.6B |

Each command is a plain function called from the CLI class; data passes
between them only through the pydantic models and files, with no shared
state.

`chunks.json` stores only the locations, not the text: entry *i* is document
*i* of the BM25 index. `answer` reads the text back from the corpus with
`text[first:last]`.

## Chunking strategy

- **Library**: `RecursiveCharacterTextSplitter` from `langchain-text-splitters`.
  It tries a list of separators from left to right and recurses into pieces
  that are still too long. The last separator is `""` (one character), so the
  size limit always holds.
- **Per file type**: Python separators for `.py` (`\nclass `, `\ndef `, ...),
  Markdown separators for `.md` (headings, code fences, rules, ...), and
  generic separators (`\n\n`, `\n`, ` `) for `.txt`.
- **Target files**: `.py`, `.md` and `.txt` of the whole repository (1969
  files). The public ground truth uses `.py`, `.md` and `CMakeLists.txt` only.
- **Size**: at most 2000 characters (the moulinette rejects any source longer
  than that), measured in characters, not tokens. Overlap: 200 characters
  (half the chunk size for chunks smaller than 400).
- **Locations**: the splitter returns text only. With `add_start_index` it
  finds the start again with `str.find`; the end is `start + len(chunk)`. A
  chunk whose location does not match its text is skipped (none in vLLM).
  The range is half-open, so `text[first:last]` is the chunk.

## Retrieval method

- **BM25** with [bm25s](https://github.com/xhluca/bm25s) (Lucene variant,
  default `k1=1.5`, `b=0.75`). The index is saved under
  `data/processed/bm25/` and loaded per command; ranking is a sparse matrix
  lookup, so a whole dataset is searched in a few seconds.
- **Tokenizer** (`src/tokenizer.py`), the same for chunks and questions:
  - words are `\w+` runs, lowercased;
  - an identifier keeps its whole form and also adds its parts, so
    `get_max_len` gives `get_max_len`, `get`, `max`, `len`, and `LLMEngine`
    gives `llmengine`, `llm`, `engine`. Questions in natural language match
    the parts; questions that name an identifier match the whole. This is the
    idea of Lucene's `word_delimiter_graph` filter with `preserve_original`;
  - one-character tokens and the 33 Lucene English stop words are dropped.
- **Ranking**: the top k chunks by BM25 score, highest first
  (`retrieve(..., sorted=True)`). A `k` larger than the number of chunks is cut
  to that number.

## Answer generation

- **Model**: Qwen/Qwen3-0.6B with `transformers` and PyTorch, loaded once per
  command. It runs in bfloat16 on a GPU or Apple MPS when one is available,
  and in float32 on the CPU otherwise.
- **Prompt**: a system message asks the model to use only the given context, to
  say so when the context does not contain the answer, to answer in a few
  sentences, and not to write links or file paths. The user message is the
  text of the retrieved chunks followed by the question.
- **Decoding**: greedy (`do_sample=False`), at most 256 new tokens, thinking
  mode off (`enable_thinking=False`), so runs are reproducible and short.

## Performance analysis

Measured on an Apple M3 Mac with the public datasets, `search_dataset --k 10`,
`max_chunk_size=2000`.

| Dataset | Recall@1 | @3 | @5 | @10 | Required @5 |
|---|---|---|---|---|---|
| docs (100 questions) | 0.600 | 0.800 | **0.870** | 0.870 | 0.80 |
| code (99 questions) | 0.444 | 0.636 | **0.677** | 0.788 | 0.50 |

| Step | Time | Limit |
|---|---|---|
| `index` (1969 files, 14638 chunks, 12 MB) | about 20 s for the whole command | 5 min |
| `search_dataset` (100 questions) | about 4 s for the whole command | 90 s for 200 questions |

Most of the command time is Python start-up and imports; the BM25 work itself
takes a few seconds. Docs questions are easier than code questions because
their wording is close to the prose of the documentation; code questions often
describe behaviour in words that do not appear in the code.

## Design decisions

- **BM25 with bm25s.** The subject asks for BM25 or TF-IDF. bm25s depends only
  on NumPy, saves and loads its index, and is fast. rank-bm25 has no saving and
  is no longer updated; retriv, pyserini and similar packages pull in heavy
  dependencies (PyTorch, Java).
- **Characters, not tokens, for the chunk size**, because the 2000 limit of the
  moulinette is in characters.
- **Only locations in `chunks.json`.** The text is already in the corpus; the
  index stays small, and the saved locations are exactly what the output needs.
- **`question_id` is copied from the input**, never regenerated, because the
  grader matches results to questions by it.
- **`file_path` relative to the working directory** (`data/raw/vllm-0.10.1/...`),
  even when `--raw_dir` is absolute, because the grader compares paths as
  strings.
- **Our own recall@k.** Libraries such as ranx match documents by ID; the
  subject's rule (same file and IoU of at least 0.05 between character ranges)
  has to be written anyway, and the rest is an average.
- **Text-only context for the model.** Adding the file path in front of each
  chunk made the model invent links; with text only, links and paths in the
  answers dropped from 11 of 11 to 2 of 14 answers in our check.
- **CPU-only PyTorch on Linux.** uv picks packages by OS and CPU, never by GPU,
  so on Linux PyPI's CUDA build pulls about 2.3 GB of NVIDIA libraries even on
  machines without one. `pyproject.toml` takes torch from PyTorch's CPU index on
  Linux; macOS keeps the PyPI build with MPS support.
- **Error handling in two layers.** The CLI checks its inputs first, because
  Fire does not convert arguments by their type hints (`abc` arrives as a
  string, `True` passes as an int, a numeric query arrives as an int). `k` and
  `max_chunk_size` must be positive integers, and the query must not be blank.
  `main()` then catches any remaining exception and prints one `Error: ...` line
  to stderr with exit code 1 (pydantic errors name the model and the field).
  Fire's own usage errors and `--help` are left to Fire. `index` skips a file
  it cannot read with a warning, fails without saving anything when there is
  nothing to index or no searchable word, and names `processed_dir` when a file
  is in its way. A failed write in `index`, `search_dataset` or
  `answer_dataset` adds a warning that the output may be incomplete.

## Challenges faced

- **The splitter does not return locations.** We rely on `add_start_index`
  (a `str.find` near the previous chunk) and check every location against the
  text.
- **Python separators assume tab indentation**, so methods indented with four
  spaces are not split at `def`, and decorators stay at the end of the previous
  chunk. The size limit still holds.
- **Fire's argument parsing** (see Design decisions), and `FireExit` being a
  `SystemExit`, which a plain `except Exception` does not break.
- **Made-up links in answers**, solved by giving the model text only.
- **The moulinette is a Linux x86-64 binary** and does not run on an Apple
  Silicon Mac, so recall was checked with our own `evaluate`, which follows
  the same rule.
- **Score-0 hits**: bm25s returns k chunks even when none contains a word of
  the question. Hits with score 0 are dropped, so a question can get fewer
  than k sources (the moulinette treats k as a maximum).
- **A half-written index**: `chunks.json` and `bm25/` must match. Everything
  that can fail (chunking, an empty vocabulary with a very small
  `--max_chunk_size`) now happens before the first write; if a write itself
  fails, a warning asks to run `index` again.
- **Known limits**: BM25 drops `not` as a stop word and ignores word order, so
  it cannot tell a question from its negation.

## Resources

- S. Robertson and H. Zaragoza, *The Probabilistic Relevance Framework: BM25
  and Beyond*, Foundations and Trends in Information Retrieval, 2009.
- X. H. Lù, *BM25S: Orders of magnitude faster lexical search via eager sparse
  scoring*, 2024, arXiv:2407.03618, and the
  [bm25s repository](https://github.com/xhluca/bm25s).
- P. Lewis et al., *Retrieval-Augmented Generation for Knowledge-Intensive NLP
  Tasks*, NeurIPS 2020.
- C. D. Manning, P. Raghavan and H. Schütze, *Introduction to Information
  Retrieval*, Cambridge University Press, 2008 (evaluation, recall).
- [LangChain text splitters](https://python.langchain.com/docs/concepts/text_splitters/)
  and the source of `langchain-text-splitters` 1.1.3.
- [Lucene `word_delimiter_graph` token filter](https://www.elastic.co/guide/en/elasticsearch/reference/current/analysis-word-delimiter-graph-tokenfilter.html).
- [Qwen/Qwen3-0.6B model card](https://huggingface.co/Qwen/Qwen3-0.6B) and the
  [transformers text generation guide](https://huggingface.co/docs/transformers/llm_tutorial).
- [Python Fire guide](https://google.github.io/python-fire/guide/) and the
  [uv documentation](https://docs.astral.sh/uv/).

### Use of AI

Claude (Anthropic's Claude Code) was used as a pair-programming assistant:

- **Research**: comparing libraries (chunking, BM25), and reading the source of
  the installed packages (langchain-text-splitters, bm25s, Fire, transformers,
  PyTorch) to confirm defaults and behaviour instead of trusting memory.
- **Explanation**: walking through the code line by line (the tokenizer
  regular expressions, BM25 storage, recall@k and IoU, the generation steps of
  transformers) until each part could be explained.
- **Code**: drafting parts of the implementation in small steps, each
  reviewed, changed or rewritten before being kept; design choices were made
  by the author.
- **Testing**: running edge cases (empty query, `k=0`, missing files,
  malformed JSON, bad paths) and measuring recall and timing.
- **Writing**: drafting this README from the project's development notes.
