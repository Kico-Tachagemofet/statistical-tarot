"""The bundled catalog contains identifiers and Chinese names only."""
from __future__ import annotations

import hashlib
from importlib.resources import files
import json

PILES = (
    ("fire", "火位", "Fire", "wands"),
    ("water", "水位", "Water", "cups"),
    ("air", "风位", "Air", "swords"),
    ("earth", "土位", "Earth", "disks"),
    ("major", "大阿卡那位", None, None),
)
COURT_RANKS = ("princess", "prince", "queen", "king")


def build_deck() -> dict[str, list[dict]]:
    """Build five canonical, ID-sorted piles without external data files."""
    names = json.loads(files(__package__).joinpath("card_names_zh.json").read_text(encoding="utf-8"))
    if not isinstance(names, dict) or len(names) != 78:
        raise ValueError("The bundled catalog must contain exactly 78 card IDs.")
    if not all(isinstance(k, str) and isinstance(v, str) and v for k, v in names.items()):
        raise ValueError("Every bundled card must have a string ID and a nonempty name.")
    piles = {key: [] for key, *_ in PILES}
    for key, _, _, suit in PILES:
        if suit is None:
            continue
        for rank in ["ace", *map(str, range(2, 11))]:
            card_id = f"{rank}_{suit}"
            piles[key].append({"id": card_id, "zh": names[card_id], "class": "minor_pip"})
        for rank in COURT_RANKS:
            card_id = f"{rank}_of_{suit}"
            piles[key].append({"id": card_id, "zh": names[card_id], "class": "court"})
    for card_id, name in names.items():
        if card_id.startswith("atu_"):
            piles["major"].append({"id": card_id, "zh": name, "class": "major_arcana"})
    actual_ids = [card["id"] for pile in piles.values() for card in pile]
    if set(actual_ids) != set(names) or len(actual_ids) != 78:
        raise ValueError("The bundled catalog has unknown or duplicate IDs.")
    if {key: len(pile) for key, pile in piles.items()} != dict.fromkeys(
        ["fire", "water", "air", "earth"], 14
    ) | {"major": 22}:
        raise ValueError("The bundled pile sizes must be 14/14/14/14/22.")
    for pile in piles.values():
        pile.sort(key=lambda card: card["id"])
    return piles


def catalog_sha256(deck: dict[str, list[dict]] | None = None) -> str:
    """Stable fingerprint of portable IDs, names and inferred classes."""
    data = json.dumps(deck if deck is not None else build_deck(), ensure_ascii=False,
                      sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()
