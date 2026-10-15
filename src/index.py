from pathlib import Path

from pydantic import TypeAdapter
from tqdm import tqdm

from .chunker import build_splitters, chunk_text
from .data_models import Chunk

TARGET_SUFFIXES: frozenset[str] = frozenset({".py", ".md", ".txt"})


def collect_files(raw_dir: Path) -> list[Path]:
    """Return target files under raw_dir, sorted by path."""
    return sorted(
        p for p in raw_dir.rglob("*")
        if p.is_file() and p.suffix in TARGET_SUFFIXES
    )


def build_index(raw_dir: str, processed_dir: str, max_chunk_size: int) -> int:
    """Chunk every target file and save the chunks; return their count."""
    splitters = build_splitters(max_chunk_size)
    chunks: list[Chunk] = []
    for path in tqdm(collect_files(Path(raw_dir)), desc="Chunking"):
        splitter = splitters[path.suffix]
        text = path.read_text(encoding="utf-8")
        chunks += chunk_text(path.as_posix(), text, splitter)
    out = Path(processed_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "chunks.json").write_bytes(
        TypeAdapter(list[Chunk]).dump_json(chunks)
    )
    return len(chunks)
