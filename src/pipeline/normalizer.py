"""Text normalization for raw memory input.

Handles whitespace cleanup, unicode normalization, and optional chunking.
"""

import unicodedata

import tiktoken


def normalize(text: str) -> str:
    """Normalize raw text for processing.

    Performs:
    - Unicode NFC normalization (canonical composition)
    - Strip leading/trailing whitespace
    - Collapse multiple blank lines to single blank line

    Args:
        text: Raw input text

    Returns:
        Normalized text
    """
    # Normalize unicode to NFC form (canonical composition)
    text = unicodedata.normalize("NFC", text)

    # Strip leading/trailing whitespace
    text = text.strip()

    # Collapse multiple blank lines into single blank line
    lines = text.split("\n")
    normalized_lines = []
    prev_blank = False

    for line in lines:
        is_blank = not line.strip()

        if is_blank:
            if not prev_blank:
                normalized_lines.append("")
            prev_blank = True
        else:
            normalized_lines.append(line)
            prev_blank = False

    return "\n".join(normalized_lines)


def chunk(text: str, max_tokens: int = 2000) -> list[str]:  # noqa: C901
    """Split text into token-bounded chunks.

    Uses tiktoken's cl100k_base tokenizer (GPT-4/Claude compatible BPE).
    Chunks are split at newline boundaries when possible to preserve structure.

    Args:
        text: Text to chunk
        max_tokens: Maximum tokens per chunk (default 2000)

    Returns:
        List of text chunks, each <= max_tokens. Returns single-element list if
        text fits in one chunk.
    """
    enc = tiktoken.get_encoding("cl100k_base")
    tokens = enc.encode(text)

    # If text fits in one chunk, return as-is
    if len(tokens) <= max_tokens:
        return [text]

    # Split by newlines first, accumulate until we exceed max_tokens
    lines = text.split("\n")
    chunks = []
    current_chunk_lines = []
    current_chunk_tokens = 0

    for line in lines:
        line_tokens = len(enc.encode(line))

        # If a single line exceeds max_tokens, split at word boundary
        if line_tokens > max_tokens:
            # Flush current chunk
            if current_chunk_lines:
                chunks.append("\n".join(current_chunk_lines))
                current_chunk_lines = []
                current_chunk_tokens = 0

            # Force-chunk the long line by words
            words = line.split()
            word_chunk = []
            for word in words:
                word_tokens = len(enc.encode(word))
                if current_chunk_tokens + word_tokens > max_tokens:
                    if word_chunk:
                        chunks.append(" ".join(word_chunk))
                    word_chunk = [word]
                    current_chunk_tokens = word_tokens
                else:
                    word_chunk.append(word)
                    current_chunk_tokens += word_tokens

            if word_chunk:
                chunks.append(" ".join(word_chunk))
                current_chunk_tokens = len(enc.encode(" ".join(word_chunk)))
        else:
            # Try to add line to current chunk
            if current_chunk_tokens + line_tokens > max_tokens:
                # Flush and start new chunk
                if current_chunk_lines:
                    chunks.append("\n".join(current_chunk_lines))
                current_chunk_lines = [line]
                current_chunk_tokens = line_tokens
            else:
                current_chunk_lines.append(line)
                current_chunk_tokens += line_tokens

    # Flush remaining
    if current_chunk_lines:
        chunks.append("\n".join(current_chunk_lines))

    return chunks if chunks else [text]
