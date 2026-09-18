"""HTTP surface for QRI, one module per area of the UI."""

from app.web import claims, daily_best, dashboard, legacy, papers, questions, themes

ROUTE_MODULES = (dashboard, themes, papers, claims, questions, daily_best, legacy)

__all__ = ["ROUTE_MODULES"]
