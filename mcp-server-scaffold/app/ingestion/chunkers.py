"""
RawUnits -> final Chunks, per the strategy doc:
  prose        -> heading already applied by loader; sliding window if long
                  (~700 words window, ~100 words overlap)
  table_row / oas_operation / oas_summary / referential_entry
               -> already atomic; pass through unchanged
"""
from dataclasses import dataclass, field
from typing import Any
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.ingestion.loaders import RawUnit

_PROSE_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=700 * 5,     # ~700 words at ~5 chars/word
    chunk_overlap=100 * 5,  # ~100-word sliding-window overlap
    separators=["\n\n", "\n", ". ", " "],
)


@dataclass
class Chunk:
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


def chunk_units(units: list[RawUnit]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for u in units:
        if not u.text.strip():
            continue
        if u.metadata.get("type") == "prose":
            for piece in _PROSE_SPLITTER.split_text(u.text):
                chunks.append(Chunk(text=piece, metadata=u.metadata))
        else:
            chunks.append(Chunk(text=u.text, metadata=u.metadata))
    return chunks
