from pathlib import Path

import bm25s
from pydantic import TypeAdapter
from tqdm import tqdm

from .chunker import build_splitters, chunk_text
from .data_models import MinimalSource
from .tokenizer import tokenize

TARGET_SUFFIXES: frozenset[str] = frozenset({".py", ".md", ".txt"})
CHUNKS_FILE = "chunks.json"
BM25_DIR = "bm25"


def collect_files(raw_dir: Path) -> list[Path]:
    """Return target files under raw_dir, sorted by path."""
    return sorted(
        p for p in raw_dir.rglob("*")
        if p.is_file() and p.suffix in TARGET_SUFFIXES
    )


def build_index(raw_dir: str, processed_dir: str, max_chunk_size: int) -> int:
    """Chunk every target file, save the chunk locations and BM25 index.

    The chunk text is only used for tokenizing and is not saved. Return the
    number of chunks. Location i in the chunks file is document i in the
    BM25 index.
    """
    splitters = build_splitters(max_chunk_size)
    sources: list[MinimalSource] = []
    tokens: list[list[str]] = []
    for path in tqdm(collect_files(Path(raw_dir)), desc="Indexing"):
        splitter = splitters[path.suffix]
        text = path.read_text(encoding="utf-8")
        for source, chunk in chunk_text(path.as_posix(), text, splitter):
            sources.append(source)
            tokens.append(tokenize(chunk))
    out = Path(processed_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / CHUNKS_FILE).write_bytes(
        TypeAdapter(list[MinimalSource]).dump_json(sources)
    )
    retriever = bm25s.BM25()
    retriever.index(tokens)
    retriever.save(str(out / BM25_DIR))
    return len(sources)
