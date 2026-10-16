"""Run lifecycle: reserve once, persist before drawing, verify before analysis."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from random import SystemRandom

from . import __version__
from .catalog import PILES, build_deck, catalog_sha256
from .statistics import build_statistics

MAX_DRAWS = 100_000
RUN_FORMAT = "statistical-tarot-run-v1"
SAMPLING_ID = "five-piles-uniform-v1"


class RunError(ValueError):
    """A run cannot safely be created, verified, analyzed, or rendered."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_draws(n: int) -> int:
    if type(n) is not int or not 1 <= n <= MAX_DRAWS:
        raise RunError(f"draws must be an integer from 1 to {MAX_DRAWS}.")
    return n


def validate_question(question: str) -> str:
    if not isinstance(question, str) or not question.strip() or len(question) > 10_000:
        raise RunError("question must be nonempty text of at most 10000 characters.")
    return question


def make_protocol(question: str, draws: int, *, synthetic: bool = False) -> dict:
    validate_question(question)
    validate_draws(draws)
    return {
        "format": RUN_FORMAT, "version": 1, "tool_version": __version__,
        "question": question, "draws": draws, "prepared_at": utc_now(),
        "synthetic": synthetic, "sampling_id": SAMPLING_ID,
        "catalog_sha256": catalog_sha256(),
        "piles": [{"key": key, "size": 22 if key == "major" else 14} for key, *_ in PILES],
        "spread": "五位置：火／水／风／土各14张，大阿卡那22张。",
        "position_semantics": "位置只表示堆归属，不指派时间、主体或因果意义。",
        "sampling": "每次等概率选五堆之一，再在该堆等概率抽一张；每次独立、有放回。",
        "random_source": "NONE: deterministic synthetic fixture" if synthetic else "Python SystemRandom; operating-system entropy; no seed",
        "orientation": "正逆独立各50%；主统计合并牌名，原始正逆保留。",
        "stopping": f"固定{draws}次；不补抽、不重抽、不续抽；输出目录不可复用。",
        "tail_definition": "含观察值的上下尾；双尾=min(1,2*min(P(X<=k),P(X>=k)))。",
        "multiplicity": "Holm按每堆分别校正，alpha=0.05；没有全78项整体校正。",
        "display_bands": {"接近基线": "|z|<1", "普通偏离": "1<=|z|<2", "极端候选": "|z|>=2"},
        "scope": "仅原始抽取及描述统计，无牌义正文或自动解读。",
    }


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def save_json_new(path: Path, value: object) -> None:
    data = json_bytes(value)
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def save_json_atomic(path: Path, value: object) -> None:
    """Replace a derived artifact only. Never used for raw records or receipts."""
    data = json_bytes(value)
    pending = path.with_name("." + path.name + ".pending")
    created = False
    try:
        with pending.open("xb") as stream:
            created = True
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, path)
    finally:
        if created and pending.exists():
            pending.unlink()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha_if_present(path: Path) -> str | None:
    try:
        return sha256_file(path) if path.is_file() else None
    except OSError:
        return None


def draw_run(question: str, out: Path, draws: int = 1000) -> dict:
    """Reserve a NEW directory and persist one non-replayable sampling run.

    Only this function creates SystemRandom. Tests replace the constructor;
    there is deliberately no public seed, resume, retry, or RNG option.
    """
    protocol = make_protocol(question, draws)
    deck = build_deck()
    out = Path(out)
    try:
        out.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise RunError("Output directory already exists; it cannot be reused or restarted. Inspect the saved run.") from exc
    completed = 0
    randomness_started = False
    try:
        save_json_new(out / "protocol.json", protocol)
        # Creating the raw file also precedes the RNG constructor.
        with (out / "raw.ndjson").open("x", encoding="utf-8", newline="\n") as stream:
            randomness_started = True  # Conservative even if construction is interrupted.
            rng = SystemRandom()
            keys = [key for key, *_ in PILES]
            for index in range(1, draws + 1):
                pile = keys[rng.randrange(len(keys))]
                card = deck[pile][rng.randrange(len(deck[pile]))]
                reversed_flag = bool(rng.getrandbits(1))
                row = {"draw": index, "pile": pile, "card_id": card["id"],
                       "zh": card["zh"], "reversed": reversed_flag}
                stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
                completed = index
        receipt = {
            "status": "completed", "completed_at": utc_now(), "draws": draws,
            "requested_draws": draws, "completed_draws": completed,
            "synthetic": False,
            "raw_sha256": sha256_file(out / "raw.ndjson"),
            "protocol_sha256": sha256_file(out / "protocol.json"),
        }
        save_json_new(out / "receipt.json", receipt)
        return receipt
    except BaseException as exc:
        partial = {
            "status": "partial", "interrupted_at": utc_now(),
            "requested_draws": draws, "completed_draws": completed,
            "randomness_started": randomness_started, "error_type": type(exc).__name__,
            "raw_sha256": _sha_if_present(out / "raw.ndjson"),
            "protocol_sha256": _sha_if_present(out / "protocol.json"),
            "policy": "Incomplete or uncertain run. Do not redraw, resume, or reuse this directory.",
        }
        try:
            target = out / ("interruption.json" if (out / "receipt.json").exists() else "receipt.json")
            save_json_new(target, partial)
        except (OSError, ValueError):
            # The reserved directory still blocks any restart. Missing/invalid
            # receipts also fail closed in analysis (including hard process kills).
            pass
        raise


def _reject_constant(value: str):
    raise RunError(f"Non-finite JSON value is not supported: {value}.")


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_constant)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise RunError(f"Invalid JSON file: {path.name}.") from exc
    if not isinstance(value, dict):
        raise RunError(f"Expected a JSON object in {path.name}.")
    return value


def _validate_protocol(protocol: dict) -> dict[str, dict[str, dict]]:
    if protocol.get("format") != RUN_FORMAT or protocol.get("sampling_id") != SAMPLING_ID:
        raise RunError("Unsupported run protocol or sampling model.")
    validate_draws(protocol.get("draws"))
    validate_question(protocol.get("question"))
    if type(protocol.get("synthetic")) is not bool:
        raise RunError("Protocol synthetic marker must be a boolean.")
    deck = build_deck()
    if protocol.get("catalog_sha256") != catalog_sha256(deck):
        raise RunError("Catalog fingerprint mismatch; do not analyze under a different deck.")
    expected_piles = [{"key": key, "size": len(deck[key])} for key, *_ in PILES]
    if protocol.get("piles") != expected_piles:
        raise RunError("Protocol pile definitions do not match the five-pile model.")
    return {key: {card["id"]: card for card in cards} for key, cards in deck.items()}


def read_completed_run(folder: Path) -> tuple[dict, dict, list[dict]]:
    folder = Path(folder)
    if not (folder / "receipt.json").is_file():
        raise RunError("No completion receipt: this run is incomplete or uncertain and cannot be analyzed or resumed.")
    receipt = read_json(folder / "receipt.json")
    if receipt.get("status") != "completed" or (folder / "interruption.json").exists():
        raise RunError("This run is incomplete or interrupted. Analysis refuses partial data; no redraw or continuation.")
    protocol_data = (folder / "protocol.json").read_bytes()
    if hashlib.sha256(protocol_data).hexdigest() != receipt.get("protocol_sha256"):
        raise RunError("Protocol SHA-256 mismatch; saved run has changed.")
    try:
        protocol = json.loads(protocol_data, parse_constant=_reject_constant)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise RunError("Invalid protocol JSON.") from exc
    if not isinstance(protocol, dict):
        raise RunError("Protocol must be a JSON object.")
    deck = _validate_protocol(protocol)
    n = protocol["draws"]
    if any(type(receipt.get(key)) is not int or receipt[key] != n
           for key in ("draws", "requested_draws", "completed_draws")):
        raise RunError("Completion receipt counts do not match the planned count.")
    if type(receipt.get("synthetic")) is not bool or receipt["synthetic"] != protocol["synthetic"]:
        raise RunError("Synthetic marker differs between protocol and receipt.")
    if not isinstance(receipt.get("completed_at"), str):
        raise RunError("Completion receipt is missing its timestamp.")
    records = []
    digest = hashlib.sha256()
    with (folder / "raw.ndjson").open("rb") as stream:
        for index, line in enumerate(stream, 1):
            if index > n or len(line) > 4096:
                raise RunError("Raw record count or record size exceeds the planned run.")
            digest.update(line)
            try:
                row = json.loads(line, parse_constant=_reject_constant)
            except (json.JSONDecodeError, UnicodeError) as exc:
                raise RunError(f"Malformed raw record {index}; the run is not complete.") from exc
            if not isinstance(row, dict) or set(row) != {"draw", "pile", "card_id", "zh", "reversed"}:
                raise RunError(f"Raw record {index} has an unsupported structure.")
            if type(row["draw"]) is not int or row["draw"] != index:
                raise RunError(f"Raw record {index} has an invalid draw sequence.")
            pile, card_id = row["pile"], row["card_id"]
            if not isinstance(pile, str) or pile not in deck or not isinstance(card_id, str) or card_id not in deck[pile]:
                raise RunError(f"Raw record {index} has an unknown card ID or the wrong pile.")
            if row["zh"] != deck[pile][card_id]["zh"] or type(row["reversed"]) is not bool:
                raise RunError(f"Raw record {index} has an invalid name or orientation.")
            records.append(row)
    if len(records) != n:
        raise RunError(f"Incomplete raw data: expected {n} records, found {len(records)}. No partial analysis.")
    if digest.hexdigest() != receipt.get("raw_sha256"):
        raise RunError("Raw SHA-256 mismatch; saved draw records have changed.")
    return protocol, receipt, records


def analyze_run(folder: Path) -> dict:
    """Verify a completed run and write only its derived statistics.json."""
    protocol, receipt, records = read_completed_run(Path(folder))
    stats = build_statistics(protocol, receipt, records)
    save_json_atomic(Path(folder) / "statistics.json", stats)
    return stats


def validate_statistics(stats: dict) -> None:
    """Validate the portable numeric schema before rendering an imported JSON."""
    if not isinstance(stats, dict):
        raise RunError("Statistics must be a JSON object.")
    validate_question(stats.get("question"))
    protocol, receipt = stats.get("protocol"), stats.get("receipt")
    if not isinstance(protocol, dict) or not isinstance(receipt, dict):
        raise RunError("Statistics require protocol and receipt objects.")
    n = validate_draws(protocol.get("draws"))
    if protocol.get("question", stats["question"]) != stats["question"]:
        raise RunError("Statistics question differs from its protocol.")
    if not isinstance(receipt.get("completed_at"), str) or receipt.get("status", "completed") != "completed":
        raise RunError("Statistics require a completed receipt.")
    piles = stats.get("piles")
    if not isinstance(piles, list) or len(piles) != 5:
        raise RunError("Statistics must contain all five piles.")
    deck = build_deck()
    total = 0

    def require_model_value(value: float, expected: float, name: str) -> None:
        if not math.isclose(value, expected, rel_tol=1e-10, abs_tol=1e-12):
            raise RunError(f"Statistics {name} does not match the fixed five-pile model.")

    for pile, (key, label, element, suit) in zip(piles, PILES):
        if not isinstance(pile, dict) or pile.get("key") != key:
            raise RunError("Statistics pile order or key is invalid.")
        if any(pile.get(field) != value for field, value in
               (("label", label), ("element", element), ("suit", suit), ("size", len(deck[key])))):
            raise RunError("Statistics pile metadata does not match the catalog.")
        cards = pile.get("cards")
        if not isinstance(cards, list) or len(cards) != len(deck[key]):
            raise RunError("Statistics must retain every card, including zero-count cards.")
        known = {card["id"]: card for card in deck[key]}
        card_p = 1 / (5 * len(known))
        card_expected = n * card_p
        card_sd = math.sqrt(n * card_p * (1 - card_p))
        seen = set()
        pile_count = 0
        for row in cards:
            if not isinstance(row, dict) or not isinstance(row.get("card_id"), str):
                raise RunError("Statistics card row is invalid.")
            card_id = row["card_id"]
            if card_id not in known or card_id in seen or row.get("zh") != known[card_id]["zh"]:
                raise RunError("Statistics contain an unknown, duplicate, or renamed card.")
            seen.add(card_id)
            for field in ("count", "upright", "reversed"):
                if type(row.get(field)) is not int or not 0 <= row[field] <= n:
                    raise RunError("Card counts must be nonnegative integers within the run size.")
            if row["upright"] + row["reversed"] != row["count"]:
                raise RunError("Orientation counts do not add up to the card count.")
            for field in ("expected", "z", "p_lower", "p_upper", "p_two", "p_holm"):
                value = row.get(field)
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise RunError("Statistics contain a missing or non-finite numeric field.")
                if field.startswith("p_") and not 0 <= value <= 1:
                    raise RunError("Statistics probability values must be between zero and one.")
            if row["expected"] <= 0:
                raise RunError("Card expected counts must be positive.")
            require_model_value(row["expected"], card_expected, "card expected count")
            require_model_value(row["z"], (row["count"] - card_expected) / card_sd, "card z")
            pile_count += row["count"]
        if type(pile.get("count")) is not int or pile_count != pile["count"]:
            raise RunError("Pile count does not equal its card counts.")
        for field in ("expected", "sd", "z", "card_expected", "card_sd"):
            if type(pile.get(field)) not in (int, float) or not math.isfinite(pile[field]):
                raise RunError("Pile metrics contain a missing or non-finite field.")
            if field != "z" and pile[field] <= 0:
                raise RunError("Pile expected counts and standard deviations must be positive.")
        pile_expected, pile_sd = n / 5, math.sqrt(n * 0.2 * 0.8)
        for field, value in (("expected", pile_expected), ("sd", pile_sd),
                             ("z", (pile_count - pile_expected) / pile_sd),
                             ("card_expected", card_expected), ("card_sd", card_sd)):
            require_model_value(pile[field], value, f"pile {field}")
        total += pile_count
    if total != n:
        raise RunError("Statistics card counts do not add up to the planned run size.")
