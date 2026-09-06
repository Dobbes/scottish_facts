from __future__ import annotations

import math
import time
from collections.abc import Callable
from typing import Any

from scotland_facts.config import Settings
from scotland_facts.research import retry_openai


def embed_text(
    client: Any,
    settings: Settings,
    text: str,
    sleep: Callable[[float], None] = time.sleep,
) -> list[float]:
    response = retry_openai(
        lambda: client.embeddings.create(
            model=settings.embedding_model,
            input=text,
            dimensions=settings.embedding_dimensions,
        ),
        sleep=sleep,
    )
    vector = list(response.data[0].embedding)
    if len(vector) != settings.embedding_dimensions:
        raise ValueError(
            f"Embedding model returned {len(vector)} dimensions; expected {settings.embedding_dimensions}"
        )
    return vector


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("Vectors must be non-empty and have equal dimensions")
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        raise ValueError("Cosine similarity is undefined for zero vectors")
    return dot / (left_norm * right_norm)
