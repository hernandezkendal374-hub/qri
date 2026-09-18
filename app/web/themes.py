"""Long-lived research themes and the community attack radar (shadow mode).

Extracted from app.main so each surface can be read on its own; the route
bodies are unchanged.
"""

from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    CommunityObservation,
    FalsificationTask,
    KnowledgeDelta,
    Paper,
    ResearchTheme,
)


def build_router(
    session_factory: Callable[[], Session],
    templates: Jinja2Templates,
) -> APIRouter:
    router = APIRouter()

    @router.get("/themes")
    def research_themes(request: Request):
        with session_factory() as session:
            themes = list(
                session.scalars(
                    select(ResearchTheme).order_by(
                        ResearchTheme.last_material_change_at.desc().nullslast(),
                        ResearchTheme.paper_count.desc(),
                    )
                )
            )
            return templates.TemplateResponse(
                request=request,
                name="themes.html",
                context={"themes": themes, "active": "themes"},
            )

    @router.get("/themes/{theme_id}")
    def research_theme_detail(request: Request, theme_id: int):
        with session_factory() as session:
            theme = session.get(ResearchTheme, theme_id)
            if not theme:
                raise HTTPException(status_code=404, detail="研究主题不存在")
            deltas = list(
                session.execute(
                    select(KnowledgeDelta, Paper)
                    .outerjoin(Paper, Paper.id == KnowledgeDelta.paper_id)
                    .where(KnowledgeDelta.theme_id == theme_id)
                    .order_by(KnowledgeDelta.created_at.desc())
                    .limit(100)
                ).all()
            )
            observations = list(
                session.scalars(
                    select(CommunityObservation)
                    .where(CommunityObservation.target_theme_id == theme_id)
                    .order_by(CommunityObservation.created_at.desc())
                    .limit(50)
                )
            )
            return templates.TemplateResponse(
                request=request,
                name="theme_detail.html",
                context={
                    "theme": theme,
                    "deltas": deltas,
                    "observations": observations,
                    "active": "themes",
                },
            )

    @router.get("/community-attack-radar")
    def community_attack_radar(request: Request):
        with session_factory() as session:
            observations = list(
                session.scalars(
                    select(CommunityObservation)
                    .order_by(CommunityObservation.created_at.desc())
                    .limit(200)
                )
            )
            tasks = list(
                session.scalars(
                    select(FalsificationTask)
                    .order_by(FalsificationTask.created_at.desc())
                    .limit(200)
                )
            )
            return templates.TemplateResponse(
                request=request,
                name="community_attack_radar.html",
                context={
                    "observations": observations,
                    "tasks": tasks,
                    "active": "community",
                    "shadow_mode": True,
                },
            )

    return router
