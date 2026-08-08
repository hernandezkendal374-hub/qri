from typing import Any

from sqlalchemy.orm import Session

from app.models import QuestionStatus, ResearchQuestion


class QuestionExportError(ValueError):
    pass


def export_candidate_question(session: Session, question: ResearchQuestion) -> dict[str, Any]:
    if question.status != QuestionStatus.HUMAN_APPROVED:
        raise QuestionExportError("Only HUMAN_APPROVED questions may be exported")
    payload = {
        "question_id": question.question_uid,
        "family": question.family,
        "question": question.question,
        "mechanism": question.economic_mechanism,
        "counter_mechanism": question.counter_mechanism,
        "literature_evidence": {
            "supporting_claim_ids": question.supporting_claims_json,
            "contradicting_claim_ids": question.contradicting_claims_json,
        },
        "required_data": question.required_data_json,
        "known_risks": question.known_risks_json,
        "status": QuestionStatus.HUMAN_APPROVED.value,
    }
    question.status = QuestionStatus.EXPORTED
    session.commit()
    return payload
