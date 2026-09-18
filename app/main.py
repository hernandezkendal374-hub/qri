"""QRI application factory.

The HTTP surface lives in app.web, one module per area of the UI. This file
only wires them together: template filters, static files, and the router list.
"""

from collections.abc import Callable

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.web import ROUTE_MODULES
from app.web.support import (
    APP_DIR,
    CLAIM_TYPE_LABELS,
    FULLTEXT_STATUS_LABELS,
    QUESTION_STATUS_LABELS,
    RESEARCH_SCOPE_LABELS,
    VERIFICATION_STATUS_LABELS,
    fulltext_reason_zh,
    local_datetime,
    local_datetime_zh,
    localized_label,
)


def _build_templates() -> Jinja2Templates:
    templates = Jinja2Templates(directory=APP_DIR / "templates")
    templates.env.filters["fulltext_status_zh"] = lambda value: localized_label(
        value, FULLTEXT_STATUS_LABELS
    )
    templates.env.filters["fulltext_reason_zh"] = fulltext_reason_zh
    templates.env.filters["question_status_zh"] = lambda value: localized_label(
        value, QUESTION_STATUS_LABELS
    )
    templates.env.filters["verification_status_zh"] = lambda value: localized_label(
        value, VERIFICATION_STATUS_LABELS
    )
    templates.env.filters["claim_type_zh"] = lambda value: localized_label(
        value, CLAIM_TYPE_LABELS
    )
    templates.env.filters["research_scope_zh"] = lambda value: localized_label(
        value, RESEARCH_SCOPE_LABELS
    )
    templates.env.filters["local_datetime"] = local_datetime
    templates.env.filters["local_datetime_zh"] = local_datetime_zh
    return templates


def create_app(session_factory: Callable[[], Session] = SessionLocal) -> FastAPI:
    web = FastAPI(title="QRI", version="0.1.0")
    templates = _build_templates()
    web.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")

    @web.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @web.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/papers", status_code=303)

    for module in ROUTE_MODULES:
        web.include_router(module.build_router(session_factory, templates))

    return web


app = create_app()
