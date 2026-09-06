from __future__ import annotations

import re
import unicodedata


TRANSLATION = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201b": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
    }
)


def normalize_fact(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).lower().translate(TRANSLATION)
    chars: list[str] = []
    for index, char in enumerate(normalized):
        if char.isalnum() or char.isspace():
            chars.append(char)
        elif char == "'" and index > 0 and index + 1 < len(normalized):
            if normalized[index - 1].isalnum() and normalized[index + 1].isalnum():
                chars.append(char)
        else:
            chars.append(" ")
    return " ".join("".join(chars).split())


def highest_semantic_match(
    neighbors: list[tuple[object, float]], threshold: float
) -> tuple[bool, object | None, float | None]:
    if not neighbors:
        return False, None, None
    matched_id, similarity = max(neighbors, key=lambda row: row[1])
    return similarity >= threshold, matched_id, similarity
