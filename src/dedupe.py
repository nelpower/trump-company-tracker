"""De-duplicate mentions of the same statement reported by multiple sources.

Strategy:
  * group by (date, normalized_company_name)
  * within a group, cluster quotes whose similarity >= threshold
  * keep the highest-quality source as the canonical record
  * record the other sources (and any extra context) in ``notes``

Identity is also enforced by the stable ``id`` (see models.compute_id), so even
without fuzzy matching a re-run never produces exact duplicates.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from src.config import SOURCE_QUALITY_RANK
from src.models import Mention

DEFAULT_THRESHOLD = 0.82


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def quote_similarity(a: str, b: str) -> float:
    """Ratio in [0, 1] between two quotes (whitespace/case-insensitive)."""
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _rank(m: Mention) -> tuple[int, int, int, str]:
    """Sort key for choosing the canonical record (higher is better).

    ``id`` is the final tiebreaker so the winner is deterministic regardless of
    input order (important for stable, idempotent merge-mode re-runs).
    """
    return (
        SOURCE_QUALITY_RANK.get(m.source_quality, 0),
        m.confidence_score,
        len(m.exact_quote or ""),
        m.id,
    )


def _merge_into(winner: Mention, loser: Mention) -> None:
    """Fold a duplicate's provenance / extra context into the winner.

    Idempotent: a note already present is not appended again, so re-running the
    pipeline over an accumulated dataset does not grow notes without bound.
    """
    existing_notes = winner.notes or ""
    bits = []
    src = loser.source_title or loser.source_url or loser.source_type
    if src:
        url = f" ({loser.source_url})" if loser.source_url else ""
        prov = f"Also reported by: {src}{url}"
        if prov not in existing_notes:
            bits.append(prov)
    # keep any context the winner happens to be missing
    if not winner.quote_context_before and loser.quote_context_before:
        winner.quote_context_before = loser.quote_context_before
    if not winner.quote_context_after and loser.quote_context_after:
        winner.quote_context_after = loser.quote_context_after
    if loser.notes and loser.notes not in existing_notes:
        bits.append(loser.notes)
    if bits:
        joined = " | ".join(bits)
        winner.notes = f"{existing_notes} | {joined}".strip(" |") if existing_notes else joined


def dedupe(
    mentions: list[Mention], threshold: float = DEFAULT_THRESHOLD
) -> list[Mention]:
    # Process in a deterministic order (by stable id) so the output does not
    # depend on how existing+new records were concatenated — this is what makes
    # merge-mode re-runs converge to a fixed point.
    for m in mentions:
        m.ensure_id()
    mentions = sorted(mentions, key=lambda m: m.id)

    # First collapse exact-id duplicates. Identical id == identical
    # (date, company, quote), so we simply keep the first and drop the rest.
    # (No note-merging here: that would bloat notes on every idempotent re-run.
    # Cross-source provenance is handled by the fuzzy clustering below.)
    by_id: dict[str, Mention] = {}
    ordered: list[Mention] = []
    for m in mentions:
        if m.id in by_id:
            continue
        by_id[m.id] = m
        ordered.append(m)

    # Group by (date, company) for fuzzy clustering.
    groups: dict[tuple[str, str], list[Mention]] = {}
    for m in ordered:
        groups.setdefault((m.date, m.normalized_company_name), []).append(m)

    result: list[Mention] = []
    for group in groups.values():
        clusters: list[list[Mention]] = []
        for m in group:
            placed = False
            for cluster in clusters:
                if quote_similarity(m.exact_quote, cluster[0].exact_quote) >= threshold:
                    cluster.append(m)
                    placed = True
                    break
            if not placed:
                clusters.append([m])

        for cluster in clusters:
            cluster.sort(key=_rank, reverse=True)
            winner = cluster[0]
            for loser in cluster[1:]:
                _merge_into(winner, loser)
            result.append(winner)

    # Stable, useful ordering: newest first, then company, then id (tiebreaker
    # so ties never reorder between runs).
    result.sort(
        key=lambda m: (m.date or "", m.normalized_company_name, m.id),
        reverse=True,
    )
    return result
