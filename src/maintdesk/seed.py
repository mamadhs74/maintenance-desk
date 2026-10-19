"""Fill a running server with INVENTED demo tickets:  python -m maintdesk.seed --url http://127.0.0.1:8000"""

from __future__ import annotations

import argparse

from .client import ApiClient
from .models import Priority, Status

DEMO = [
    ("Ölstand zu niedrig", "Presse P-12", "Ölstand liegt unter der Markierung, Nachfüllen nötig.", Priority.HIGH),
    ("Förderband läuft unruhig", "Förderband F-3", "Ruckeln bei Volllast, Lager prüfen.", Priority.NORMAL),
    ("Sensor meldet falsche Temperatur", "Ofen O-1", "Abweichung von etwa 8 Grad zum Referenzthermometer.", Priority.HIGH),
    ("Schutzhaube klemmt", "Fräse M-7", "", Priority.LOW),
    ("Jährliche Wartung planen", "Kompressor K-2", "Termin mit dem Hersteller abstimmen.", Priority.LOW),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    client = ApiClient(args.url)
    created = [client.create_ticket(*row) for row in DEMO]
    client.set_status(created[1].id, Status.IN_PROGRESS, "A. Beispiel")
    client.set_status(created[1].id, Status.DONE)
    client.set_status(created[2].id, Status.IN_PROGRESS, "B. Beispiel")
    print(f"created {len(created)} demo tickets")


if __name__ == "__main__":
    main()
