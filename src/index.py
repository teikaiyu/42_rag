from pathlib import Path


TARGET_SUFFIXES: frozenset[str] = frozenset({".py", ".md"})
TARGET_FILENAMES: frozenset[str] = frozenset({"CMakelists.txt"})


def is_target_file(path: Path) -> bool:
    """Return True if the file should be indexed."""
    return path.suffix in TARGET_SUFFIXES or path.name in TARGET_FILENAMES


def collect_files(raw_dir: str = "data/raw") -> list[Path]:
    """Collect target files under raw_dir, sorted by path."""
    root = Path(raw_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"Raw data directory not found: {raw_dir}")
    return sorted(
        p for p in root.rglob("*") if p.is_file() and is_target_file(p)
    )
