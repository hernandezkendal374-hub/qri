"""The Scout cap must keep the highest-scoring rows, not an arbitrary subset.

RadarService.assess used to collect eligible ids into a set and slice that,
which discarded the ranking.  Small integers hash to their own value, so the
slice kept the lowest ids -- the oldest papers -- and silently dropped the
highest-scoring candidates.  The bug only showed once more candidates passed
the threshold than SCOUT_MAX_ITEMS allowed, which is exactly the daily-300
workload the funnel is built for.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import build_engine
from app.models import Paper, RadarAssessment
from app.radar import RadarService


def _session() -> Session:
    engine = build_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


# assess() walks papers newest-first (Paper.id DESC), so the paper listed
# first here is assessed last and receives the highest RadarAssessment id.
# Strongest first therefore puts the best candidates on the highest ids,
# which is what separates a real ranking from insertion order.
_PAPERS = [
    (
        "Institutional crowding reverses documented quality premia",
        "The premium shows reversal and decay once crowding is accounted for. "
        "Replication on point-in-time data with a placebo design, survivorship "
        "correction, look-ahead controls, and explicit transaction cost "
        "assumptions overturns the published estimate across every subsample "
        "we examine, including out-of-sample periods and alternative universes.",
    ),
    (
        "Machine-learning return prediction fails out of sample",
        "The published effect fails to replicate. Performance shows decay "
        "after publication. We run a placebo design, correct for survivorship "
        "bias, and report out-of-sample results.",
    ),
    (
        "Short-sale constraints and borrow fee dynamics",
        "Borrowing costs decay over the period. We use a placebo design and "
        "adjust for survivorship bias in the sample.",
    ),
    (
        "Liquidity provision and price impact in modern venues",
        "We measure price impact with a placebo design and correct for "
        "survivorship in the universe.",
    ),
    (
        "Earnings announcement drift under attention constraints",
        "We study announcement drift and run a placebo test on the sample.",
    ),
    (
        "Cross-sectional dispersion of US equity returns",
        "We describe dispersion across the cross section of returns.",
    ),
]


def _seed(session: Session) -> None:
    for title, abstract in _PAPERS:
        session.add(
            Paper(
                title=title,
                normalized_title=title.lower(),
                abstract=abstract,
                source="test",
                research_scope="US_EQUITY_CORE",
            )
        )
    session.commit()


def test_scout_cap_keeps_the_highest_scoring_rows() -> None:
    session = _session()
    try:
        _seed(session)
        cap = 3
        rows = RadarService(session).assess(scout_limit=cap, threshold=0.0)

        eligible = [row for row in rows if row.change_type != "LOW_INCREMENTAL_VALUE"]
        expected = {
            row.id
            for row in sorted(
                eligible,
                key=lambda item: (item.incremental_value_score, item.id),
                reverse=True,
            )[:cap]
        }
        promoted = {row.id for row in rows if row.decision == "SCOUT"}

        assert len(promoted) == cap
        assert promoted == expected

        # The regression: the old code kept the lowest ids instead of the best
        # scores.  Only a meaningful test if those two sets actually differ.
        lowest_ids = {row.id for row in sorted(eligible, key=lambda item: item.id)[:cap]}
        assert expected != lowest_ids, "fixture no longer distinguishes rank from insertion order"
        assert promoted != lowest_ids
    finally:
        session.close()


def test_every_row_below_the_cap_is_archived() -> None:
    session = _session()
    try:
        _seed(session)
        rows = RadarService(session).assess(scout_limit=2, threshold=0.0)
        decisions = {row.decision for row in rows}
        assert decisions <= {"SCOUT", "ARCHIVED"}
        assert sum(row.decision == "SCOUT" for row in rows) == 2
        stored = session.query(RadarAssessment).count()
        assert stored == len(_PAPERS)
    finally:
        session.close()


def test_cap_of_zero_promotes_nothing() -> None:
    session = _session()
    try:
        _seed(session)
        rows = RadarService(session).assess(scout_limit=0, threshold=0.0)
        assert all(row.decision == "ARCHIVED" for row in rows)
    finally:
        session.close()
