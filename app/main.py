from fastapi import FastAPI

from app.routers.jobs import router as jobs_router
from app.routers.web import router as web_router

app = FastAPI(title="Content AI Agent", version="1.0.0")
app.include_router(jobs_router)
app.include_router(web_router)
