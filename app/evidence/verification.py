from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Evidence, ResearchCard
from app.schemas.research import PaperResearchCard


def field_verification_status(session: Session, card: ResearchCard, field_name: str) -> str:
    if field_name not in PaperResearchCard.model_fields:
        raise ValueError(f"Unknown Research Card field: {field_name}")
    evidence_id = session.scalar(
        select(Evidence.id)
        .where(
            Evidence.paper_id == card.paper_id,
            Evidence.research_card_field == field_name,
        )
        .limit(1)
    )
    return "VERIFIED" if evidence_id is not None else "UNVERIFIED"
