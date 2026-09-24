from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.api.router import router
from app.api.exception_handlers import marinade_exception_handler, general_exception_handler
from app.core.database import get_engine, Base
from app.core.config import settings
from app.utils.logging import get_logger
from app.utils.exceptions import MarinadeException
import app.models  # register every model with SQLAlchemy metadata

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
    description="""
    Marinade API est une plateforme de gestion d’abonnements, de transactions et de restauration.

    Elle permet de gérer :
    - l’authentification des utilisateurs et des rôles d’accès,
    - les abonnements et leurs soldes quotidiens,
    - les transactions financières et les paiements par terminal ou système externe,
    - la gestion des restaurants, menus, catégories, plats, boissons, tables et commandes,
    - la centralisation des notifications d’entreprise par email, SMS et WhatsApp.

    Cette API est conçue pour un usage professionnel avec des contrôles d’accès par rôle,
    des validations métier, des flux d’authentification JWT, ainsi qu’une structure orientée
    microservices et intégration de passerelles de paiement.
    """,
    version=settings.APP_VERSION,
    lifespan=lifespan,
    debug=settings.DEBUG,
    openapi_tags=[
        {
            "name": "authentication",
            "description": "Endpoints d’authentification, création de compte, connexion, rafraîchissement des tokens et déconnexion."
        },
        {
            "name": "users",
            "description": "Gestion des utilisateurs, profils, rôle admin/pos et opérations de maintenance sur les comptes."
        },
        {
            "name": "subscriptions",
            "description": "Gestion des souscriptions actives, statuts et suivi des comptes abonnés."
        },
        {
            "name": "subscription-tiers",
            "description": "Gestion des offres commerciales, prix, limites et niveaux d’abonnement disponibles."
        },
        {
            "name": "subscription-balances",
            "description": "Suivi des soldes quotidiens, historique de consommation et réinitialisation journalière."
        },
        {
            "name": "transactions",
            "description": "Historique des transactions et opérations de paiement liées aux abonnements et au point de vente."
        },
        {
            "name": "restaurants",
            "description": "Gestion des établissements et de leur identité commerciale."
        },
        {
            "name": "restaurant-menus",
            "description": "Gestion des menus, organisation des cartes et structure commerciale du restaurant."
        },
        {
            "name": "restaurant-categories",
            "description": "Gestion des catégories de menu pour organiser les plats et les boissons."
        },
        {
            "name": "restaurant-plats",
            "description": "Gestion des plats, prix, ingrédients, disponibilité et fiche produit."
        },
        {
            "name": "restaurant-boissons",
            "description": "Gestion de la carte boissons, prix, disponibilité et proposition commerciale."
        },
        {
            "name": "restaurant-tables",
            "description": "Gestion du plan de salle, occupation, disponibilité et positionnement des tables."
        },
        {
            "name": "restaurant-orders",
            "description": "Gestion des commandes clients, items, statut de commande et suivi de service."
        },
        {
            "name": "restaurant-combinations",
            "description": "Gestion des composants, combinaisons tarifées, suppléments et recommandations de repas selon la disponibilité."
        },
        {
            "name": "restaurant-stock",
            "description": "Consultation du stock physique et réservé, mouvements d'inventaire et disponibilité opérationnelle des composants."
        },
        {
            "name": "health",
            "description": "Contrôle de santé de l’application et vérification du statut de disponibilité du service."
        }
    ],
    swagger_ui_parameters={"persistAuthorization": True}
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


@app.get(
    "",
    summary="Informations générales de l’API",
    description="""
    Retourne les informations de base de l’application et le point d’entrée de la documentation Swagger.

    Cette route est utile pour vérifier rapidement que l’API est démarrée et pour connaître la version active.
    """,
    tags=["health"],
    responses={200: {"description": "Informations générales de l’API retournées avec succès."}}
)
def root():
    return {
        "message": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "environment": settings.ENVIRONMENT
    }


@app.get(
    "/health",
    summary="Vérifier la santé de l’application",
    description="""
    Contrôle le statut de disponibilité de l’API.

    Cette route est utilisée pour les probes de santé, le monitoring et les vérifications d’infra.
    """,
    tags=["health"],
    responses={200: {"description": "L’application est disponible et répond correctement."}}
)
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
