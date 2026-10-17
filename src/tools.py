"""
Tools for the InsureEase Claims Intake Agent.

Every function takes plain arguments and returns a plain dict, mirroring
the shape of a real LLM tool-call result. This layer has zero dependency
on any LLM or API - it's pure Python, fully unit-testable offline, and is
shared by both Rung 4 (fixed workflow) and the future Rung 5 (ReAct agent).

Risk tiers (mirrors the write-action-capping pattern):
  GREEN  - read-only lookups, no risk
  YELLOW - write action, hard-capped in code, every call logged
  BLUE   - terminal/external action, always permitted
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data"))

from datetime import datetime
from seed_data import POLICIES, CLAIMS, CLAIM_HISTORY, COVERAGE_POLICY_SECTIONS

MAX_ADVANCE_USD = 500.0  # hard cap, enforced in code below, not just in a prompt

WRITE_ACTION_LOG: list[dict] = []  # every issue_claim_advance call gets appended here


def get_policy_status(policy_id: str) -> dict:
    """GREEN / READ. Policy lookup by ID."""
    policy = POLICIES.get(policy_id)
    if policy is None:
        return {"error": "policy_not_found", "policy_id": policy_id}
    return {
        "policy_id": policy.policy_id,
        "holder_name": policy.holder_name,
        "coverage_type": policy.coverage_type.value,
        "status": policy.status.value,
        "effective_date": policy.effective_date.isoformat(),
        "expiry_date": policy.expiry_date.isoformat(),
    }


_STOPWORDS = {
    "a", "an", "the", "of", "or", "and", "to", "in", "on", "at", "by", "for",
    "with", "no", "any", "is", "are", "be", "may", "must", "that", "this",
    "regardless", "provided", "however", "other", "own", "up", "as", "from",
}


def _tokenize(text: str) -> list[str]:
    cleaned = text.lower().replace(",", "").replace(".", "").replace("-", " ")
    return [w for w in cleaned.split() if w not in _STOPWORDS and len(w) > 2]


# crude inverse-document-frequency weighting: words that appear in fewer
# sections score higher when matched, so common domain words like "claim"
# or "policy" (which appear in almost every section) don't drown out the
# actually-distinguishing terms like "injury" or "lapsed".
def _build_idf_weights() -> dict[str, float]:
    doc_count = len(COVERAGE_POLICY_SECTIONS)
    word_doc_freq: dict[str, int] = {}
    for text in COVERAGE_POLICY_SECTIONS.values():
        for word in set(_tokenize(text)):
            word_doc_freq[word] = word_doc_freq.get(word, 0) + 1
    return {word: doc_count / freq for word, freq in word_doc_freq.items()}


_IDF_WEIGHTS = _build_idf_weights()


MIN_MATCH_SCORE = 10.0  # kept as a secondary ranking signal among sections
# that already pass the diagnostic-keyword gate below - no longer the sole
# gate on its own. See DIAGNOSTIC_KEYWORDS for why.

# Curated, per-section words that are genuinely specific to that section's
# topic - not derived from document-frequency statistics. This is the fix
# for a real finding: on a corpus this small (6 sections), IDF weighting
# can mistake a word that's merely STRUCTURALLY rare (appears in only one
# section by coincidence) for one that's SEMANTICALLY diagnostic. The word
# "comprehensive" is a concrete example - it appears only in
# collision_coverage's text ("...with comprehensive or collision
# coverage..."), so IDF scores it as if it specifically indicated a
# collision claim, when it's actually just a generic policy-type word that
# could legitimately appear in almost any claim's query. That coincidence
# gave an unrelated theft-claim query ("comprehensive theft coverage
# stolen property") the exact same score as a genuine short collision
# query ("collision coverage parking lot fender-bender") - both 7.50,
# meaning no threshold value could have separated them. A query must now
# contain at least one of a section's actual diagnostic words before that
# section can be returned at all, regardless of its IDF score.
DIAGNOSTIC_KEYWORDS: dict[str, set[str]] = {
    "collision_coverage": {"collision", "impact", "fender", "crash", "accident"},
    "liability_only_limits": {"liability"},
    "storm_and_water_exclusion": {"storm", "water", "wind", "flood", "rain", "hurricane"},
    "claim_frequency_review": {"frequency", "multiple", "prior", "repeated"},
    "lapsed_policy_handling": {"lapsed", "expired", "expiry", "inactive"},
    "injury_and_bodily_harm": {"injury", "injured", "bodily", "harm", "hurt", "whiplash"},
}


def search_coverage_policy(query: str) -> dict:
    """GREEN / READ. Keyword search over the coverage policy doc.

    Two-stage matching, not pure score ranking:
      1. GATE: the query must contain at least one of the target section's
         curated diagnostic words (see DIAGNOSTIC_KEYWORDS) - a section
         that fails this gate is never returned, no matter how high its
         IDF score is.
      2. RANK: among sections that pass the gate, IDF-weighted overlap
         score (see MIN_MATCH_SCORE) breaks ties and ranks multiple
         plausible matches.

    This is a fix for a real finding: an earlier score-only version
    returned collision_coverage for a theft claim (the CLM-105 finding),
    and after raising the score threshold to fix that, a second, different
    bug appeared - a short, entirely legitimate collision query started
    failing to match at all, because IDF weighting on this small corpus
    can't reliably tell a genuinely diagnostic word from a coincidentally
    rare one. See README.md's Findings section for the full story.

    Still a stand-in for real embedding-based search, not a guarantee -
    DIAGNOSTIC_KEYWORDS is a curated list, not exhaustive, and a
    genuinely novel claim-type phrasing not covered by these words could
    still fail to match even when a real corresponding section exists.
    """
    query_words = set(_tokenize(query))
    scored: list[tuple[float, int, str]] = []

    for section, text in COVERAGE_POLICY_SECTIONS.items():
        diagnostic = DIAGNOSTIC_KEYWORDS.get(section, set())
        if not (query_words & diagnostic):
            continue  # gate: no diagnostic word present, skip regardless of score

        section_words = set(_tokenize(text))
        overlap = query_words & section_words
        score = sum(_IDF_WEIGHTS.get(w, 1.0) for w in overlap)
        scored.append((score, len(overlap), section))

    if not scored:
        return {"section": None, "text": ""}
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    best_section = scored[0][2]
    return {"section": best_section, "text": COVERAGE_POLICY_SECTIONS[best_section]}


def get_claim_history(policy_id: str) -> dict:
    """GREEN / READ. Prior claims on this policy, for frequency/fraud signal."""
    events = CLAIM_HISTORY.get(policy_id, [])
    paid_count = sum(1 for e in events if e.status == "paid")
    return {
        "policy_id": policy_id,
        "claim_count": len(events),
        "paid_claim_count": paid_count,
        "claims": [
            {
                "claim_id": e.claim_id,
                "filed_at": e.filed_at.isoformat(),
                "claim_type": e.claim_type,
                "amount_usd": e.amount_usd,
                "status": e.status,
            }
            for e in events
        ],
    }


def get_weather_event_data(location: str, date: str) -> dict:
    """GREEN / READ. Confirms a declared storm/catastrophe event.

    Stubbed with a small fixture rather than a real weather API,
    since this is offline-only for now.
    """
    fixture = {
        ("Tampa, FL", "2026-07-19"): {
            "event_declared": True,
            "event_type": "severe_thunderstorm",
            "peak_wind_mph": 68,
        },
    }
    result = fixture.get((location, date))
    if result is None:
        return {"event_declared": False, "location": location, "date": date}
    return {"location": location, "date": date, **result}


def get_police_report_status(claim_id: str) -> dict:
    """GREEN / READ. Whether a police report was filed for this claim."""
    claim = CLAIMS.get(claim_id)
    if claim is None:
        return {"error": "claim_not_found", "claim_id": claim_id}
    return {
        "claim_id": claim_id,
        "filed": claim.police_report_filed,
        "reference_number": f"PR-{claim_id[-3:]}-2026" if claim.police_report_filed else None,
    }


def check_deductible(policy_id: str) -> dict:
    """GREEN / READ. Remaining deductible for this policy year."""
    policy = POLICIES.get(policy_id)
    if policy is None:
        return {"error": "policy_not_found", "policy_id": policy_id}
    return {
        "policy_id": policy_id,
        "annual_deductible_usd": policy.annual_deductible_usd,
        "deductible_used_usd": policy.deductible_used_usd,
        "deductible_remaining_usd": policy.deductible_remaining(),
    }


def issue_claim_advance(claim_id: str, amount_usd: float) -> dict:
    """YELLOW / WRITE. Hard-capped at MAX_ADVANCE_USD in code, not just prompt.

    Over-cap requests are rejected outright. Every call is logged.
    """
    if amount_usd > MAX_ADVANCE_USD:
        return {"error": "cap_exceeded", "requested_usd": amount_usd, "max_usd": MAX_ADVANCE_USD}
    entry = {
        "claim_id": claim_id,
        "amount_usd": amount_usd,
        "issued_at": datetime.now().isoformat(),
    }
    WRITE_ACTION_LOG.append(entry)
    return {"advance_issued": True, "claim_id": claim_id, "amount_usd": amount_usd, "currency": "USD"}


def escalate_to_adjuster(reason: str) -> dict:
    """BLUE / EXTERNAL. Terminal action, always permitted."""
    return {"escalated": True, "reason": reason}
