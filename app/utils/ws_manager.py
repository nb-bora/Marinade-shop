"""Flux temps réel des écrans cuisine/bar (KDS).

Contrat WebSocket
-----------------
Connexion : ``/v1/ros/ws/kds/{restaurant_id}/{station}`` avec ``station`` parmi
``KITCHEN``, ``BAR``, ``DESSERT`` ; jeton dans le sous-protocole
(``new WebSocket(url, ["bearer", accessToken])``) ou l'en-tête Authorization.

Le serveur pousse un message texte JSON à chaque création ou changement de statut d'un
ticket de CETTE station, une fois la transaction validée :

    {
      "event": "ticket.created" | "ticket.updated",
      "occurred_at": "2026-10-08T10:15:00+00:00",
      "restaurant_id": "<uuid>",
      "station": "KITCHEN",
      "ticket": {
        "id": "<uuid>", "order_id": "<uuid>", "station": "KITCHEN",
        "status": "QUEUED" | "IN_PREPARATION" | "READY" | "SERVED",
        "items_jsonb": [{"product_name": "...", "quantity": 1, "notes": null}],
        "created_at": "...", "ready_at": null
      }
    }

Le message est autosuffisant (pas de relecture nécessaire). Le client peut envoyer
``ping`` : le serveur répond ``pong`` (le délai d'inactivité des proxys est ainsi tenable).
Un ticket annulé par un rollback n'est jamais diffusé.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List
from fastapi import WebSocket
import json
import logging

from sqlalchemy import event, inspect as sa_inspect, text

from app.models.ros import ProductionTicket

logger = logging.getLogger(__name__)
_QUEUE_KEY = "kds_events"


class KdsConnectionManager:
    def __init__(self):
        # Maps (restaurant_id, station) -> List[WebSocket]
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(
        self,
        websocket: WebSocket,
        restaurant_id: str,
        station: str,
        subprotocol: str | None = None,
    ):
        await websocket.accept(subprotocol=subprotocol)
        key = f"{restaurant_id}:{station}"
        if key not in self.active_connections:
            self.active_connections[key] = []
        self.active_connections[key].append(websocket)

    def disconnect(self, websocket: WebSocket, restaurant_id: str, station: str):
        key = f"{restaurant_id}:{station}"
        if key in self.active_connections:
            if websocket in self.active_connections[key]:
                self.active_connections[key].remove(websocket)
            if not self.active_connections[key]:
                del self.active_connections[key]

    async def broadcast_ticket_event(
        self, restaurant_id: str, station: str, event_data: dict
    ):
        key = f"{restaurant_id}:{station}"
        if key in self.active_connections:
            message = json.dumps(event_data, default=str)
            for connection in list(self.active_connections[key]):
                try:
                    await connection.send_text(message)
                except Exception:
                    # Connexion morte : on la retire pour ne plus lui écrire.
                    self.disconnect(connection, restaurant_id, station)


kds_manager = KdsConnectionManager()


# --------------------------------------------------------------------------- #
# Détection des changements de tickets (ORM) -> file d'événements de la session
# --------------------------------------------------------------------------- #
def _plain(value: Any) -> Any:
    """Valeur d'une énumération (``BAR``), pas son nom (``ProductionStation.BAR``)."""
    return getattr(value, "value", value)


def _payload(ticket: ProductionTicket) -> Dict[str, Any]:
    state = ticket.__dict__
    return {
        "id": ticket.id,
        "order_id": ticket.order_id,
        "station": _plain(ticket.station),
        "status": _plain(ticket.status),
        "items_jsonb": ticket.items_jsonb,
        "created_at": state.get("created_at") or datetime.now(timezone.utc),
        "ready_at": state.get("ready_at"),
    }


def _queue(target: ProductionTicket, name: str) -> None:
    from sqlalchemy.orm import object_session

    session = object_session(target)
    if session is None:
        return
    queue: Dict[Any, dict] = session.info.setdefault(_QUEUE_KEY, {})
    previous = queue.get(target.id)
    if previous is not None and previous["event"] == "ticket.created":
        name = "ticket.created"  # créé puis modifié dans la même transaction
    queue[target.id] = {
        "event": name,
        "occurred_at": datetime.now(timezone.utc),
        "restaurant_id": target.restaurant_id,
        "station": _plain(target.station),
        "ticket": _payload(target),
    }


@event.listens_for(ProductionTicket, "after_insert")
def _ticket_inserted(mapper, connection, target):
    _queue(target, "ticket.created")


@event.listens_for(ProductionTicket, "after_update")
def _ticket_updated(mapper, connection, target):
    if sa_inspect(target).attrs.status.history.has_changes():
        _queue(target, "ticket.updated")


def drain_kds_events(db) -> List[dict]:
    """Événements à diffuser, à appeler JUSTE AVANT le commit.

    Écarte ceux dont le ticket n'existe plus (point de sauvegarde annulé pendant la
    transaction) : un cuisinier ne doit jamais voir un ticket qui n'existera pas.
    """
    queue = db.info.pop(_QUEUE_KEY, None)
    if not queue:
        return []
    try:
        rows = db.execute(
            text("SELECT id FROM production_tickets WHERE id = ANY(:ids)"),
            {"ids": list(queue)},
        ).all()
    except Exception:
        logger.exception("KDS: impossible de vérifier les tickets, diffusion annulée")
        return []
    alive = {row[0] for row in rows}
    return [event_data for ticket_id, event_data in queue.items() if ticket_id in alive]


def publish_kds_events(events: List[dict]) -> None:
    """Diffuse après le commit, sans jamais faire échouer la requête.

    Appelé depuis un thread de FastAPI (routes synchrones) : ``anyio.from_thread`` y
    ramène l'exécution dans la boucle d'événements où vivent les WebSockets.
    """
    if not events:
        return
    try:
        import anyio.from_thread
    except ImportError:  # pragma: no cover
        return
    for data in events:
        try:
            anyio.from_thread.run(
                kds_manager.broadcast_ticket_event,
                str(data["restaurant_id"]),
                str(data["station"]),
                data,
            )
        except RuntimeError:
            # Hors boucle (script, test synchrone) : rien à diffuser, personne n'écoute.
            logger.debug("KDS: pas de boucle d'événements, diffusion ignorée")
            return
        except Exception:
            logger.exception("KDS: échec de diffusion")
