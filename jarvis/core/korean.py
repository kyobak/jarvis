"""Tiny Korean text helpers."""

from __future__ import annotations


def has_batchim(word: str) -> bool:
    """True if the last Hangul syllable ends in a final consonant."""
    for ch in reversed(word.strip()):
        if "가" <= ch <= "힣":
            return (ord(ch) - 0xAC00) % 28 != 0
        if ch.isdigit():
            # Spoken digits: 0 영, 1 일, 3 삼, 6 육, 7 칠, 8 팔 end in a consonant.
            return ch in "013678"
        if ch.isascii() and ch.isalpha():
            # English words as Koreans read them: Gmail(메일), Slack(슬랙), Zoom(줌) end in a
            # consonant; Spotify(파이), Claude(로드), Jarvis(비스) do not. Heuristic, not exact.
            return ch.lower() in "lmnkpgb"
        if ch.isalpha():
            return False
    return False


def copula(word: str) -> str:
    """word + 이에요/예요."""
    return f"{word}{'이에요' if has_batchim(word) else '예요'}"


def topic(word: str) -> str:
    """word + 은/는."""
    return f"{word}{'은' if has_batchim(word) else '는'}"


def join_and(items: list[str]) -> str:
    """["A", "B", "C"] -> "A, B, C"."""
    return ", ".join(items)
