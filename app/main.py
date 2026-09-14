from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.api.router import router
from app.api.exception_handlers import marinade_exception_handler, general_exception_handler
from app.core.database import get_engine, Base
from app.core.config import settings
from app.utils.logging import get_logger
from app.utils.exceptions import MarinadeException
# Import models to register them with SQLAlchemy metadata
from app.models import user, subscription, transaction

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"Environment: {settings.ENVIRONMENT}")

    try:
        if settings.SKIP_DB_INIT:
            logger.info("Skipping database initialization")
        else:
            engine = get_engine()
            Base.metadata.create_all(bind=engine)
            logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Could not create database tables: {e}")
        logger.info("Please run Alembic migrations instead: alembic upgrade head")

    yield

    # Shutdown
    logger.info("Application shutdown")


# Create the FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    description="API de gestion d'abonnements et transactions",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    debug=settings.DEBUG
)

# Add exception handlers
app.add_exception_handler(MarinadeException, marinade_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.ALLOW_CREDENTIALS,
    allow_methods=settings.cors_methods,
    allow_headers=settings.cors_headers,
)

# Include the API router
app.include_router(router)


@app.get("/")
def root():
    return {
        "message": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "environment": settings.ENVIRONMENT
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION
    }


if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting server on {settings.HOST}:{settings.PORT}")
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
