"""v1 API router."""

from fastapi import APIRouter

from app.api.v1 import (
    ai,
    auth,
    campaigns,
    catalog,
    cycles,
    dashboard,
    feedback,
    insights,
    lookup,
    masters,
    orgs,
    proposals,
    public,
    reports,
    settings as settings_api,
    users,
)

api_router = APIRouter(prefix="/api/v1")
# Unauthenticated respondent routes first: they must never be shadowed by a
# path that expects a bearer token.
api_router.include_router(public.router)
api_router.include_router(auth.router)
api_router.include_router(orgs.router)
api_router.include_router(users.router)
api_router.include_router(catalog.router)
api_router.include_router(cycles.router)
api_router.include_router(cycles.assignments_router)
api_router.include_router(cycles.me_router)
api_router.include_router(campaigns.router)
api_router.include_router(campaigns.contacts_router)
api_router.include_router(campaigns.targets_router)
api_router.include_router(feedback.router)
api_router.include_router(proposals.router)
api_router.include_router(ai.router)
api_router.include_router(insights.router)
api_router.include_router(dashboard.router)
api_router.include_router(lookup.router)
api_router.include_router(masters.departments_router)
api_router.include_router(masters.job_titles_router)
api_router.include_router(masters.cycle_names_router)
api_router.include_router(reports.router)
api_router.include_router(settings_api.router)
