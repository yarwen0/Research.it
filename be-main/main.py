import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.api import router as research_router
from config import CORS_ORIGINS


# Create FastAPI app
app = FastAPI(
    title="Research Gap Discovery Engine API",
    description="API for extracting research parameters and discovering gaps",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,  # configurable via CORS_ORIGINS env; defaults to "*"
    allow_credentials=True,
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
            "research": "/api/research"
        }
    }


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info"
    )
