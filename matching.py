"""
matching.py — deterministic + LLM market matching.

Pipeline:
  1. Keyword overlap pre-filter (fast, no API, <2 s)
  2. Deterministic scoring: dates, entities, slugs, categories
  3. LLM confirmation (optional, batched) for candidates above a lower threshold
  4. Returns only pairs with confidence >= MATCH_CONFIDENCE

Rejected near-matches are logged with reasons.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from exchanges.base import MarketInfo

log = logging.getLogger(__name__)

STOP_WORDS = {
    "will", "the", "a", "an", "in", "on", "at", "to", "of", "be",
    "by", "or", "and", "is", "it", "for", "this", "that", "with",
    "above", "below", "than", "who", "what", "when", "win", "wins",
    "per", "over", "under", "has", "have", "are", "was", "were",
    "not", "but", "from", "out", "his", "her", "its", "most", "more",
    "than", "yes", "no", "did", "does", "get", "got",
}


@dataclass
class MatchedPair:
    kalshi: MarketInfo
    poly: MarketInfo
    confidence: float
    match_reasons: list[str] = field(default_factory=list)


@dataclass
class RejectedPair:
    kalshi: MarketInfo
    poly: MarketInfo
    best_score: float
    reason: str


# ── Text normalisation ────────────────────────────────────────────────────────

_YEAR_RE = re.compile(r"\b(202[0-9])\b")
_NUMBER_RE = re.compile(r"\b(\d+(?:\.\d+)?)\b")


def _normalize(text: str) -> set[str]:
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    words = [w for w in text.split() if w not in STOP_WORDS and len(w) > 2]
    return set(words)


def _keyword_overlap(a: str, b: str) -> float:
    wa, wb = _normalize(a), _normalize(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / max(len(wa), len(wb))


def _extract_year(text: str) -> Optional[str]:
    m = _YEAR_RE.search(text)
    return m.group(1) if m else None


def _extract_numbers(text: str) -> set[str]:
    return set(_NUMBER_RE.findall(text.lower()))


# ── Deterministic scoring ─────────────────────────────────────────────────────

def _det_score(k: MarketInfo, p: MarketInfo) -> tuple[float, list[str]]:
    """
    Deterministic confidence score in [0, 1].
    Returns (score, [reasons]).
    """
    reasons: list[str] = []
    score = 0.0

    kw = _keyword_overlap(k.title, p.title)
    score += kw * 0.70
    if kw >= 0.6:
        reasons.append(f"keyword_overlap={kw:.2f}")

    # Year match / mismatch
    ky, py = _extract_year(k.title), _extract_year(p.title)
    if ky and py:
        if ky == py:
            score += 0.10
            reasons.append(f"year_match={ky}")
        else:
            score -= 0.20
            reasons.append(f"year_mismatch({ky}vs{py})")

    # Numbers match (point spreads, percentages, etc.)
    kn = _extract_numbers(k.title)
    pn = _extract_numbers(p.title)
    if kn and pn:
        common = kn & pn
        if common:
            score += 0.10
            reasons.append(f"numbers_match={common}")
        elif kn and pn and not common:
            score -= 0.10
            reasons.append("numbers_mismatch")

    # Category match
    if k.category and p.category:
        if k.category.lower() == p.category.lower():
            score += 0.05
            reasons.append("category_match")

    # Close time proximity (within 7 days)
    if k.close_time and p.close_time:
        try:
            from datetime import datetime
            fmt = "%Y-%m-%dT%H:%M:%SZ"
            kt = datetime.strptime(k.close_time[:19] + "Z", fmt)
            pt = datetime.strptime(p.close_time[:19] + "Z", fmt)
            delta_days = abs((kt - pt).days)
            if delta_days <= 1:
                score += 0.15
                reasons.append("close_time_match")
            elif delta_days <= 7:
                score += 0.05
                reasons.append(f"close_time_near({delta_days}d)")
            else:
                score -= 0.10
                reasons.append(f"close_time_far({delta_days}d)")
        except Exception:
            pass

    return round(min(max(score, 0.0), 1.0), 4), reasons


# ── LLM verification ──────────────────────────────────────────────────────────

def _llm_confirm(candidates: list[tuple[MarketInfo, MarketInfo, float]], api_key: str) -> dict[tuple[str,str], float]:
    """
    Ask Claude Haiku to confirm candidate pairs.
    Returns {(kalshi_id, poly_id): llm_confidence}.
    """
    if not candidates or not api_key:
        return {}

    try:
        import anthropic
    except ImportError:
        return {}

    pairs = [
        {
            "kalshi_title": k.title,
            "kalshi_ticker": k.market_id,
            "kalshi_close": k.close_time,
            "poly_title": p.title,
            "poly_slug": p.market_id,
            "poly_close": p.close_time,
            "det_score": round(s, 2),
        }
        for k, p, s in candidates[:80]
    ]

    prompt = f"""You are verifying whether Kalshi and Polymarket prediction market pairs resolve on EXACTLY the same event and outcome.

For each pair, return:
- "match": true/false
- "confidence": 0.0–1.0
- "reason": one short sentence

PAIRS:
{json.dumps(pairs, indent=2)}

Return ONLY JSON array:
[{{"kalshi_ticker": "X", "poly_slug": "Y", "match": true, "confidence": 0.95, "reason": "..."}}]
"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        results = json.loads(text[text.find("[") : text.rfind("]") + 1])
        out = {}
        for r in results:
            if r.get("match"):
                out[(r["kalshi_ticker"], r["poly_slug"])] = float(r.get("confidence", 0.8))
        log.info(f"[LLM] confirmed {len(out)}/{len(pairs)} pairs")
        return out
    except Exception as e:
        log.warning(f"[LLM] confirmation failed: {e}")
        return {}


# ── Public API ────────────────────────────────────────────────────────────────

def match_markets(
    kalshi_markets: list[MarketInfo],
    poly_markets: list[MarketInfo],
    anthropic_api_key: str = "",
    confidence_threshold: float = 0.80,
) -> tuple[list[MatchedPair], list[RejectedPair]]:
    """
    Match Kalshi markets to Polymarket equivalents.

    Returns (matched_pairs, rejected_near_misses).
    """
    matched: list[MatchedPair] = []
    rejected: list[RejectedPair] = []

    # Pre-normalise poly titles
    poly_norm = [(p, _normalize(p.title)) for p in poly_markets]

    # Step 1: fast keyword pre-filter
    llm_candidates: list[tuple[MarketInfo, MarketInfo, float]] = []
    used_poly: set[str] = set()

    for k in kalshi_markets:
        kw = _normalize(k.title)
        if not kw:
            continue

        # Find best poly match by keyword overlap
        best_kw, best_p = 0.0, None
        for p, pw in poly_norm:
            if not pw:
                continue
            ov = len(kw & pw) / max(len(kw), len(pw))
            if ov > best_kw:
                best_kw = ov
                best_p = p

        if best_p is None or best_kw < 0.25:
            continue

        # Step 2: deterministic scoring
        det, reasons = _det_score(k, best_p)

        if det >= confidence_threshold:
            matched.append(MatchedPair(k, best_p, det, reasons + ["det_only"]))
            used_poly.add(best_p.market_id)
        elif det >= 0.10:
            # Needs LLM confirmation
            llm_candidates.append((k, best_p, det))
        else:
            if best_kw >= 0.30:
                rejected.append(RejectedPair(k, best_p, det, f"score_too_low({det:.2f})"))

    # Step 3: LLM verification for borderline candidates
    if llm_candidates and anthropic_api_key:
        llm_results = _llm_confirm(llm_candidates, anthropic_api_key)
        for k, p, det in llm_candidates:
            key = (k.market_id, p.market_id)
            llm_conf = llm_results.get(key, 0.0)
            combined = round(det * 0.4 + llm_conf * 0.6, 4)
            if combined >= confidence_threshold:
                matched.append(MatchedPair(k, p, combined, [f"det={det:.2f}", f"llm={llm_conf:.2f}"]))
            else:
                rejected.append(RejectedPair(k, p, combined, f"llm_failed(combined={combined:.2f})"))
    elif llm_candidates:
        # No LLM key — use deterministic score only for borderline
        for k, p, det in llm_candidates:
            rejected.append(RejectedPair(k, p, det, "no_llm_key_borderline"))

    # Deduplicate: each poly market used at most once
    seen_poly: set[str] = set()
    deduped: list[MatchedPair] = []
    for mp in sorted(matched, key=lambda x: x.confidence, reverse=True):
        if mp.poly.market_id not in seen_poly:
            seen_poly.add(mp.poly.market_id)
            deduped.append(mp)

    log.info(
        f"[Matching] {len(kalshi_markets)} Kalshi × {len(poly_markets)} Poly "
        f"→ {len(deduped)} matched, {len(rejected)} rejected near-misses"
    )
    return deduped, rejected
