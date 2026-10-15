from langchain_text_splitters import Language, RecursiveCharacterTextSplitter

from .data_models import Chunk


def build_splitters(
        max_chunk_size: int
) -> dict[str, RecursiveCharacterTextSplitter]:
    """Return a splitter per target file suffix."""
    def for_language(language: Language) -> RecursiveCharacterTextSplitter:
        return RecursiveCharacterTextSplitter.from_language(
            language, chunk_size=max_chunk_size, add_start_index=True
        )
    return {
        ".py": for_language(Language.PYTHON),
        ".md": for_language(Language.MARKDOWN),
        ".txt": RecursiveCharacterTextSplitter(
            chunk_size=max_chunk_size, add_start_index=True
        ),
    }


def chunk_text(
        file_path: str, text: str, splitter: RecursiveCharacterTextSplitter
) -> list[Chunk]:
    """Split text into chunks whose span satisfies text[first:last]."""
    chunks = []
    for doc in splitter.create_documents([text]):
        start: int = doc.metadata["start_index"]
        chunks.append(Chunk(
            file_path=file_path,
            first_character_index=start,
            last_character_index=start + len(doc.page_content),
            text=doc.page_content,
        ))
    return chunks
