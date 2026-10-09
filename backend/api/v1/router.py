from fastapi import APIRouter
from backend.api.v1.auth import auth_router
from backend.api.v1.cases import router as cases_router

api_v1_router = APIRouter()
api_v1_router.include_router(auth_router)
api_v1_router.include_router(cases_router, tags=["cases"])
