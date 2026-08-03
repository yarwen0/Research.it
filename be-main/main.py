import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from api.api import router as research_router
from config import CORS_ALLOW_CREDENTIALS, CORS_ORIGINS, HOST, PORT
from db.bootstrap import ensure_schema
from rate_limit import limiter, rate_limit_handler

# Configured once, at the entry point. A library module calling basicConfig
# would silently depend on being imported before anything else logs.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Bring the schema up to date before serving, so a fresh clone or a new
    # container needs no separate migration step.
    ensure_schema()
    yield


# Create FastAPI app
app = FastAPI(
    title="Research Gap Discovery Engine API",
    description="API for extracting research parameters and discovering gaps",
    version="1.0.0",
    lifespan=lifespan,
)

# Rate limiting. SlowAPIMiddleware applies the default per-client budget to
# every route; the expensive endpoints add their own tighter limits on top.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
app.add_middleware(SlowAPIMiddleware)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,  # configurable via CORS_ORIGINS env; defaults to "*"
    allow_credentials=CORS_ALLOW_CREDENTIALS,  # off while origins are wildcarded
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(research_router, prefix="/api", tags=["research"])


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "ok",
        "message": "Research Gap Discovery Engine API is running",
        "version": "1.0.0"
    }


@app.get("/health")
async def health_check():
    """Detailed health check endpoint"""
    return {
        "status": "healthy",
        "service": "Research Gap Discovery Engine",
        "endpoints": {
            "research": "/api/research",
            "create_review": "/api/create_review",
            "reviews": "/api/reviews",
            "review": "/api/reviews/{review_id}",
            "compile_latex": "/api/latex/compile",
            "graph": "/api/graph/{project_id}/",
        }
    }


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=HOST,
        port=PORT,
        reload=False,
        log_level="info"
    )
