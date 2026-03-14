"""Embedding generation for memory content."""

import structlog

from src.llm.client import EmbeddingFailed, VoyageEmbeddingClient

logger = structlog.get_logger(__name__)


async def embed_text(
    text: str,
    client: VoyageEmbeddingClient,
) -> list[float]:
    """Generate embedding vector for text.

    Args:
        text: Text to embed
        client: VoyageEmbeddingClient instance to use

    Returns:
        List of 1024 floats representing the embedding

    Raises:
        EmbeddingFailed: If embedding fails after retries
    """
    try:
        embedding = await client.embed(text)

        logger.info(
            "embed_text_success",
            text_len=len(text),
            embedding_dims=len(embedding),
        )

        return embedding

    except EmbeddingFailed:
        raise
    except Exception as e:
        logger.exception("embed_text_unexpected_error", error=str(e))
        raise EmbeddingFailed(f"Unexpected error during embedding: {e}") from e
