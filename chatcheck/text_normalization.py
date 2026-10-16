"""Conservative text normalization for opt-in Urdu phrase matching only."""

import unicodedata


def normalize_phrase(text):
    text = unicodedata.normalize("NFC", text)
    # Arabic/Persian yeh and kaf share code points with common Urdu variants.
    # Bari yeh is a distinct Urdu letter and is deliberately retained.
    text = text.translate(str.maketrans({"\u064a": "\u06cc", "\u0649": "\u06cc", "\u0643": "\u06a9"}))
    text = "".join(char for char in text
                   if unicodedata.category(char) not in {"Mn", "Me", "Cf"}
                   and char not in {"\u034f", "\u180e"})
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())
