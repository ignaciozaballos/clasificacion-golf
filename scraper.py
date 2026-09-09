#!/usr/bin/env python3
"""
Scraper de hándicaps RFEGolf para un grupo de amigos.

Consulta https://rfegolf.es/PaginasServicios/ServicioHandicap.aspx para cada
persona listada en friends.json, guarda un histórico semanal en
data/history.json y escribe data/latest.json con el ranking actual y la
tendencia (subida/bajada/igual) respecto a la semana anterior.

Pensado para ejecutarse desde GitHub Actions una vez a la semana, pero puede
lanzarse también en local con: python scraper.py
"""

import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://rfegolf.es/PaginasServicios/ServicioHandicap.aspx"
ROOT = Path(__file__).resolve().parent
FRIENDS_FILE = ROOT / "friends.json"
HISTORY_FILE = ROOT / "data" / "history.json"
LATEST_FILE = ROOT / "data" / "latest.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


def strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def parse_handicap(raw: str) -> float | None:
    """'26,9' -> 26.9. Devuelve None si no es un número (p.ej. 'N/D')."""
    raw = raw.strip().replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def parse_fecha(raw: str) -> str | None:
    """'12-08-2026' -> '2026-08-12' (ISO), para poder ordenar/comparar."""
    raw = raw.strip()
    try:
        return datetime.strptime(raw, "%d-%m-%Y").date().isoformat()
    except ValueError:
        return None


def fetch_player(friend: dict) -> dict:
    """Lanza la consulta a la RFEG y extrae la fila que coincide con la licencia esperada."""
    params = {
        "HNom": friend["nombre"],
        "HAp1": friend["apellido1"],
        "HAp2": friend.get("apellido2", ""),
    }

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

    try:
        resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        result["error"] = f"fallo de red: {exc}"
        return result

    soup = BeautifulSoup(resp.text, "html.parser")

    # La tabla de resultados es un GridView de ASP.NET; su id termina en
    # "gvSearchResult". Cada fila de datos tiene 5 celdas:
    # Nombre | Licencia | Handicap | Estado | Fecha modificación
    table = soup.find(id=re.compile(r"gvSearchResult$"))
    if table is None:
        result["error"] = "no se encontró la tabla de resultados (¿cambió la web?)"
        return result

    rows = table.find_all("tr")
    candidate = None
    all_candidates = []
    expected_lic = re.sub(r"\s+", "", friend.get("licencia_esperada", "")).upper()
    lic_pattern = re.compile(r"^[A-Za-z]{1,3}\d{4,}$")

    for row in rows:
        cells = [c.get_text(strip=True) for c in row.find_all("td")]
        if len(cells) < 5:
            continue  # fila de cabecera u otra cosa

        # La tabla incluye columnas vacías de maquetación (botones, etc.) antes
        # y después de los datos, así que la licencia no está siempre en la
        # misma posición. La localizamos por su formato (letras + números) y
        # leemos el resto de columnas en relación a ella.
        lic_idx = None
        for i, c in enumerate(cells):
            if lic_pattern.fullmatch(c):
                lic_idx = i
                break
        if lic_idx is None or lic_idx < 1 or lic_idx + 3 >= len(cells):
            continue

        nombre = cells[lic_idx - 1]
        licencia = cells[lic_idx]
        handicap = cells[lic_idx + 1]
        estado = cells[lic_idx + 2]
        fecha = cells[lic_idx + 3]

        all_candidates.append((nombre, licencia, handicap, estado, fecha))

        lic_norm = re.sub(r"\s+", "", licencia).upper()
        if expected_lic and lic_norm != expected_lic:
            continue
        candidate = (nombre, licencia, handicap, estado, fecha)
        break

    if candidate is None:
        if all_candidates:
            found = "; ".join(f"{n} ({l})" for n, l, h, e, f in all_candidates)
            result["error"] = (
                f"no se encontró una fila que coincida con la licencia esperada "
                f"'{expected_lic}'. Filas encontradas: {found}"
            )
        else:
            result["error"] = "no se encontró ninguna fila de datos reconocible en la tabla"
        return result

    nombre, licencia, handicap, estado, fecha = candidate
    result["nombre"] = nombre
    result["licencia"] = licencia
    result["handicap"] = parse_handicap(handicap)
    result["handicap_display"] = handicap
    result["estado"] = estado
    result["ultima_modificacion"] = parse_fecha(fecha)
    result["ultima_modificacion_display"] = fecha
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
