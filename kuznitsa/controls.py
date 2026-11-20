"""Интерфейс правил магазина между поиском и аналитикой."""
import re
from .text import normalize


class Controls:
    def version(self) -> int:
        return 0

    def synonyms(self) -> list[dict]:
        return []

    def weights(self) -> dict | None:
        return None

    def redirect(self, ctx: dict) -> dict | None:
        return None

    def merch(self, ctx: dict, cards: list[dict]) -> dict:
        return {"cards": cards, "banners": [], "fired": []}


class PhraseRules:
    def __init__(self, rules):
        self.by_phrase = {normalize(r["phrase"]): r for r in rules if r["phrase"].strip()}
        phrases = sorted(self.by_phrase, key=len, reverse=True)
        self.pattern = re.compile(r"(?<!\w)(?:" + "|".join(map(re.escape, phrases)) + r")(?!\w)") if phrases else None

    def apply(self, text):
        fired = []
        def substitute(match):
            rule = self.by_phrase[match[0]]
            fired.append(rule)
            return normalize(rule["to"])
        return (self.pattern.sub(substitute, text) if self.pattern else text), fired
