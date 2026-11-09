"""Déploie le service Render et vérifie que l'API ET la base de données fonctionnent.

Appelé par .github/workflows/ci-deploy.yml, uniquement après des tests verts sur main.

Étapes :
  1. Demande à Render un nouveau déploiement du service.
  2. Attend que le déploiement soit « live » (ou échoue).
  3. Vérifie que le commit déployé est bien celui du pipeline (GITHUB_SHA).
  4. Vérifie /health (processus up) puis /health/ready (requête SQL réelle + RLS).

Variables d'environnement :
  RENDER_API_KEY      clé API Render (secret GitHub)
  RENDER_SERVICE_ID   identifiant du service, ex. srv-xxxx (secret GitHub)
  RENDER_SERVICE_URL  URL publique, ex. https://marinade-api.onrender.com (variable GitHub)
  EXPECTED_COMMIT     SHA du commit à déployer (GITHUB_SHA)

Aucun secret n'est affiché dans les journaux.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://api.render.com/v1"
DEPLOY_TIMEOUT_S = 30 * 60
POLL_EVERY_S = 15
HEALTH_TIMEOUT_S = 6 * 60

TERMINAL_OK = {"live"}
TERMINAL_FAIL = {
    "build_failed",
    "update_failed",
    "pre_deploy_failed",
    "canceled",
    "deactivated",
}


def log(message: str) -> None:
    print(message, flush=True)


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        log(f"ERREUR : variable d'environnement manquante : {name}")
        sys.exit(1)
    return value


def render_request(method: str, path: str, token: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"{API}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode() or "{}"
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise RuntimeError(f"Render API {method} {path} -> HTTP {exc.code}: {detail}") from exc


def trigger_deploy(token: str, service_id: str) -> str:
    result = render_request("POST", f"/services/{service_id}/deploys", token, {})
    deploy_id = result.get("id")
    if not deploy_id:
        raise RuntimeError(f"Réponse Render inattendue (pas d'id de déploiement) : {result}")
    log(f"Déploiement demandé : {deploy_id}")
    return deploy_id


def wait_for_deploy(token: str, service_id: str, deploy_id: str, expected_commit: str) -> None:
    deadline = time.monotonic() + DEPLOY_TIMEOUT_S
    last_status = None
    while time.monotonic() < deadline:
        deploy = render_request("GET", f"/services/{service_id}/deploys/{deploy_id}", token)
        status = deploy.get("status", "unknown")
        if status != last_status:
            log(f"  statut Render : {status}")
            last_status = status

        if status in TERMINAL_OK:
            deployed_commit = (deploy.get("commit") or {}).get("id", "")
            if not deployed_commit:
                log("  avertissement : Render n'a pas renvoyé le commit déployé, vérification ignorée.")
            elif not expected_commit.startswith(deployed_commit) and deployed_commit != expected_commit:
                raise RuntimeError(
                    f"Le commit déployé ({deployed_commit[:12]}) n'est pas celui du pipeline "
                    f"({expected_commit[:12]})."
                )
            else:
                log(f"  commit déployé confirmé : {deployed_commit[:12]}")
            return
        if status in TERMINAL_FAIL:
            raise RuntimeError(f"Le déploiement a échoué (statut : {status}). Voir les journaux dans Render.")
        time.sleep(POLL_EVERY_S)
    raise RuntimeError("Délai dépassé en attendant la fin du déploiement Render.")


def check_endpoint(base_url: str, path: str, expected_status: str) -> None:
    """Interroge l'endpoint avec des tentatives : un service gratuit peut être en veille au réveil."""
    url = f"{base_url.rstrip('/')}{path}"
    deadline = time.monotonic() + HEALTH_TIMEOUT_S
    last_error = "aucune réponse"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                payload = json.loads(response.read().decode() or "{}")
                if response.status == 200 and payload.get("status") == expected_status:
                    log(f"  {path} : OK ({payload})")
                    return
                last_error = f"HTTP {response.status} {payload}"
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")[:300]
            last_error = f"HTTP {exc.code} {body}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = str(exc)
        time.sleep(POLL_EVERY_S)
    raise RuntimeError(f"{path} n'est pas prêt : {last_error}")


def main() -> int:
    token = require_env("RENDER_API_KEY")
    service_id = require_env("RENDER_SERVICE_ID")
    service_url = require_env("RENDER_SERVICE_URL")
    expected_commit = require_env("EXPECTED_COMMIT")

    try:
        log("1. Déploiement Render")
        deploy_id = trigger_deploy(token, service_id)
        wait_for_deploy(token, service_id, deploy_id, expected_commit)

        log("2. Vérification de l'API")
        check_endpoint(service_url, "/health", expected_status="healthy")

        log("3. Vérification API + base de données (requête SQL réelle, RLS)")
        check_endpoint(service_url, "/health/ready", expected_status="ready")
    except RuntimeError as exc:
        log(f"ÉCHEC : {exc}")
        return 1

    log("Déploiement vérifié : API et base de données opérationnelles.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
