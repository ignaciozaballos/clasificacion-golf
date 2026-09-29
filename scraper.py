#!/usr/bin/env python3
"""
Scraper de hándicaps RFEGolf para un grupo de amigos.

NOTA (2026-09-29): la RFEG rediseñó por completo su web de consulta de
hándicap. La antigua página ServicioHandicap.aspx (que se consultaba por
nombre y apellidos, devolviendo una tabla HTML) ha dejado de funcionar.
La nueva consulta vive en https://rfegolf.es/aprende-mejora/consulta-handicap
y busca por licencia federativa a través de una API JSON pública
(Typesense por detrás), que es lo que este script consulta ahora.

Para cada persona listada en friends.json (usando su "licencia_esperada"),
consulta esa API, guarda un histórico semanal en data/history.json y
escribe data/latest.json con el ranking actual y la tendencia
(subida/bajada/igual) respecto a la semana anterior.

Pensado para ejecutarse desde GitHub Actions una vez a la semana, pero puede
lanzarse también en local con: python scraper.py
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

API_URL = "https://rfegolf.es/wp-json/handicap-search/v1/search"
ROOT = Path(__file__).resolve().parent
FRIENDS_FILE = ROOT / "friends.json"
HISTORY_FILE = ROOT / "data" / "history.json"
LATEST_FILE = ROOT / "data" / "latest.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://rfegolf.es/aprende-mejora/consulta-handicap",
}

# Solo tenemos confirmado que 1 = federado con hándicap válido/activo.
# Cualquier otro código se muestra tal cual (sin inventar una etiqueta)
# para que se note en la web si aparece un caso distinto.
FEDERATED_STATUS = {
    1: "Válido",
}


def parse_handicap(raw) -> float | None:
    """'26.9' (float o string) -> 26.9. Devuelve None si no es un número."""
    if raw is None:
        return None
    try:
        return float(str(raw).replace(",", "."))
    except ValueError:
        return None


def fmt_handicap_display(value: float | None) -> str | None:
    if value is None:
        return None
    # Estilo español con coma decimal, como mostraba la web antigua.
    return f"{value:.1f}".replace(".", ",")


def parse_fecha_iso(raw) -> str | None:
    """La API ya devuelve la fecha en formato ISO (YYYY-MM-DD)."""
    if not raw:
        return None
    try:
        datetime.strptime(raw, "%Y-%m-%d")
        return raw
    except ValueError:
        return None


def fmt_fecha_display(iso: str | None) -> str | None:
    if not iso:
        return None
    y, m, d = iso.split("-")
    return f"{d}-{m}-{y}"


def fetch_player(friend: dict) -> dict:
    """Busca a la persona en la API de la RFEG por su licencia (o, si no hay
    licencia guardada, por su nombre completo) y devuelve sus datos."""

    expected_lic = friend.get("licencia_esperada", "").strip().upper()
    query = expected_lic or (
        f"{friend['nombre']} {friend['apellido1']} {friend.get('apellido2', '')}".strip()
    )

    result = {
        "id": friend["id"],
        "nombre": None,
        "licencia": None,
        "handicap": None,
        "handicap_display": None,
        "estado": None,
        "ultima_modificacion": None,
        "ultima_modificacion_display": None,
        "error": None,
    }

    if not query:
        result["error"] = "sin licencia ni nombre para buscar en friends.json"
        return result

    try:
        resp = requests.get(
            API_URL,
            params={"q": query, "size": 5},
            headers=HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError) as exc:
        result["error"] = f"fallo de red o respuesta no válida de la API: {exc}"
        return result

    hits = ((payload.get("data") or {}).get("hits")) or []
    if not hits:
        result["error"] = "la API de la RFEG no devolvió ningún resultado para esta búsqueda"
        return result

    candidate = None
    all_found = []
    for hit in hits:
        doc = hit.get("document") or {}
        lic = (doc.get("guid_licence") or "").strip().upper()
        all_found.append(f"{doc.get('full_name')} ({lic})")
        if expected_lic and lic != expected_lic:
            continue
        candidate = doc
        break

    if candidate is None:
        if expected_lic:
            result["error"] = (
                f"ninguno de los resultados coincide con la licencia esperada "
                f"'{expected_lic}'. Encontrados: {'; '.join(all_found)}"
            )
            return result
        # Sin licencia guardada (fallback por nombre): usamos el primer
        # resultado, avisando de que es menos fiable que buscar por licencia.
        candidate = hits[0].get("document") or {}

    handicap_val = parse_handicap(candidate.get("handicap"))
    status_code = candidate.get("enum_federated_status")

    result["nombre"] = candidate.get("full_name")
    result["licencia"] = candidate.get("guid_licence")
    result["handicap"] = handicap_val
    result["handicap_display"] = fmt_handicap_display(handicap_val)
    result["estado"] = (
        FEDERATED_STATUS.get(status_code, f"Estado {status_code}")
        if status_code is not None
        else None
    )
    result["ultima_modificacion"] = parse_fecha_iso(candidate.get("date_hdc_updated_at"))
    result["ultima_modificacion_display"] = fmt_fecha_display(result["ultima_modificacion"])
    return result


def load_json(path: Path, default):
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    return default


def compute_ranks(players: list[dict]) -> list[dict]:
    """Ordena por hándicap ascendente (menor hándicap = mejor jugador) y asigna 'rank'."""
    ranked = sorted(
        [p for p in players if p.get("handicap") is not None],
        key=lambda p: p["handicap"],
    )
    unranked = [p for p in players if p.get("handicap") is None]

    for i, p in enumerate(ranked, start=1):
        p["rank"] = i
    for p in unranked:
        p["rank"] = None
    return ranked + unranked


def main() -> int:
    friends = load_json(FRIENDS_FILE, [])
    if not friends:
        print("friends.json está vacío, nada que hacer.", file=sys.stderr)
        return 1

    current_players = [fetch_player(f) for f in friends]
    current_players = compute_ranks(current_players)

    history = load_json(HISTORY_FILE, [])
    prev_snapshot = history[-1] if history else None
    prev_ranks = {}
    if prev_snapshot:
        for p in prev_snapshot.get("players", []):
            prev_ranks[p["id"]] = p.get("rank")

    for p in current_players:
        prev_rank = prev_ranks.get(p["id"])
        p["prev_rank"] = prev_rank
        if p.get("rank") is None or prev_rank is None:
            p["trend"] = "new"
        elif p["rank"] < prev_rank:
            p["trend"] = "up"       # ha adelantado a alguien
        elif p["rank"] > prev_rank:
            p["trend"] = "down"     # le han adelantado
        else:
            p["trend"] = "same"

    timestamp = datetime.now(timezone.utc).isoformat()
    snapshot = {"generated_at": timestamp, "players": current_players}

    history.append(snapshot)
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY_FILE.open("w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    with LATEST_FILE.open("w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    errors = [p for p in current_players if p.get("error")]
    if errors:
        print(f"Aviso: {len(errors)} jugador(es) con error:", file=sys.stderr)
        for p in errors:
            print(f"  - {p['id']}: {p['error']}", file=sys.stderr)

    print(f"OK. {len(current_players)} jugadores procesados.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
