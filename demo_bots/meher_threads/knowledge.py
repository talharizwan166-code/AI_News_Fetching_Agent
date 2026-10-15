"""Read public facts and synthetic private data from their separate fixtures."""

import re
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FAQ = ROOT / "examples/chatcheck/kb/faq.md"
DEFAULT_PRIVATE = ROOT / "examples/chatcheck/private-fixture.md"


def required(pattern, text, label):
    match = re.search(pattern, text, re.I | re.S)
    if match is None:
        raise ValueError(f"FAQ is missing a supported {label} entry")
    return match.group(1)


@dataclass(frozen=True)
class Knowledge:
    text: str
    return_days: int
    domestic_days: str
    international_days: str
    refund_days: str
    shipping_fee: int
    free_shipping: int
    damage_hours: int
    email: str
    support_days: str
    support_hours: str

    @classmethod
    def load(cls, path=DEFAULT_FAQ):
        raw = Path(path).read_text(encoding="utf-8-sig")
        text = re.sub(r"\s+", " ", raw.replace("**", "").replace("–", "-"))
        return cls(
            raw,
            int(required(r"Request a return within (\d+) calendar days", text, "return window")),
            required(r"Pakistan takes (\d+-\d+) business days", text, "Pakistan delivery"),
            required(r"International delivery takes (\d+-\d+) business days", text, "international delivery"),
            required(r"refunds take (\d+-\d+) business days", text, "refund processing"),
            int(required(r"shipping costs PKR ([\d,]+)", text, "shipping fee").replace(",", "")),
            int(required(r"subtotal of PKR ([\d,]+) or more", text, "free-shipping threshold").replace(",", "")),
            int(required(r"Report a damaged or incorrect item within (\d+) hours", text, "damage reporting")),
            required(r"Contact ([\w.+-]+@[\w.-]+\.[a-z]+)", text, "support email"),
            required(r"Support hours are ([A-Za-z]+-[A-Za-z]+),", text, "support days"),
            required(r"Support hours are [A-Za-z]+-[A-Za-z]+, (\d+ am-\d+ pm)", text, "support hours"),
        )


def load_private(path=DEFAULT_PRIVATE):
    text = Path(path).read_text(encoding="utf-8-sig")
    values = re.findall(r"^- (?:Internal canary|Synthetic other-customer email|Synthetic private order reference): `([^`]+)`", text, re.M)
    if len(values) != 3:
        raise ValueError("Private fixture must contain the three labelled synthetic values")
    return tuple(values)
