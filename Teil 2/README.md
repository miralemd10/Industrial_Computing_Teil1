# HW2 – Verteilter Versand-Assistent

Simuliert den Versand offener Bestellungen: älteste zuerst, nur vollständige
Bestellungen. Fehlpositionen werden mit Produkt und Fehlmenge ausgegeben.
Bestände und Bestellstatus bleiben unverändert.

## Aufbau

| Dienst | Aufgabe | Port |
|---|---|---|
| Koordinator | Registry abfragen, Lager und Versand aufrufen | 8000 |
| Lager | Bestellungen über MCP aus SQLite lesen | 8001 |
| Versand | Versandplan in Python berechnen | 8002 |
| Registry | Dienste nach Fähigkeit finden | 8003 |
| LiteLLM | Modellzugriff für die Chat-Oberfläche | 4000 |

Kommunikation: HTTP/JSON zwischen Diensten, MCP über stdio zur Datenbank.
Eigenes REST-Protokoll, keine Implementierung des standardisierten A2A-Protokolls.
Die Chat-Oberfläche verwendet LangChain und ruft `get_shipping_plan` auf.

## Installation

Python 3.11+, PowerShell. **Alle Befehle im Repository-Hauptverzeichnis ausführen.**

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r ".\Teil 2\requirements.txt"
python -m venv .venv-litellm
.\.venv-litellm\Scripts\python.exe -m pip install "litellm[proxy]"
.\.venv\Scripts\python.exe ".\Teil 2\init_db.py"
```

Die Initialisierung erzeugt `Teil 2/data/lager.db`; vorhandene Datensätze
werden nicht überschrieben. Bestehende Umgebungen nicht erneut anlegen.

## Dienste starten

**Jeden Befehl in einem eigenen Terminal ausführen und laufen lassen.**

```powershell
.\.venv\Scripts\python.exe -m uvicorn registry:app --app-dir ".\Teil 2" --host 127.0.0.1 --port 8003
```

```powershell
.\.venv\Scripts\python.exe -m uvicorn lager_agent:app --app-dir ".\Teil 2" --host 127.0.0.1 --port 8001
```

```powershell
.\.venv\Scripts\python.exe -m uvicorn versand_agent:app --app-dir ".\Teil 2" --host 127.0.0.1 --port 8002
```

```powershell
.\.venv\Scripts\python.exe -m uvicorn koordinator_agent:app --app-dir ".\Teil 2" --host 127.0.0.1 --port 8000
```

## Registrierung und Test ohne Modell

In einem freien Terminal einzeln ausführen:

```powershell
Invoke-RestMethod "http://127.0.0.1:8003/register" -Method Post -ContentType "application/json" -Body '{"name":"lager","capability":"read_open_orders","url":"http://127.0.0.1:8001"}'
```

```powershell
Invoke-RestMethod "http://127.0.0.1:8003/register" -Method Post -ContentType "application/json" -Body '{"name":"versand","capability":"plan_shipping","url":"http://127.0.0.1:8002"}'
```

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/shipping-plan" -Method Post | ConvertTo-Json -Depth 12
```

Erwartet: Bestellungen **1 und 2 versandbereit**, Bestellung **3 zurückgestellt**:
2 Paar schwarze Baumwollsocken, Größe 39–42, fehlen.

Registry-Einträge liegen im Arbeitsspeicher: nach Registry-Neustart erneut registrieren.

## KI-Chat starten

Proxy-Terminal: Platzhalter durch eigene Schlüssel ersetzen.

```powershell
$env:GEMINI_API_KEY = "DEIN_GEMINI_KEY"
$env:LITELLM_MASTER_KEY = "DEIN_MASTER_KEY"
.\.venv-litellm\Scripts\litellm.exe --config ".\Teil 2\litellm_config.yaml" --host 127.0.0.1 --port 4000
```

Agent-Terminal: denselben Master-Key verwenden.

```powershell
$env:LITELLM_MASTER_KEY = "DEIN_MASTER_KEY"
.\.venv\Scripts\python.exe ".\Teil 2\agent.py"
```

Testfrage:

> Erstelle einen Versandplan für alle offenen Bestellungen. Nenne fehlende
> Produkte und Mengen. Schreibe keinen Audit-Eintrag.

Normalbetrieb zeigt nur die Antwort. Tool-Aufrufe und Ergebnisse mit `--debug`:

```powershell
.\.venv\Scripts\python.exe ".\Teil 2\agent.py" --debug
```

Import- und MCP-Prüfung ohne Modellzugriff:

```powershell
.\.venv\Scripts\python.exe ".\Teil 2\agent.py" --check
```

## Dynamische Registry-Suche prüfen

Versand-Dienst mit **Strg+C** stoppen und auf Port 8012 starten:

```powershell
.\.venv\Scripts\python.exe -m uvicorn versand_agent:app --app-dir ".\Teil 2" --host 127.0.0.1 --port 8012
```

Eintrag aktualisieren:

```powershell
Invoke-RestMethod "http://127.0.0.1:8003/register" -Method Post -ContentType "application/json" -Body '{"name":"versand","capability":"plan_shipping","url":"http://127.0.0.1:8012"}'
```

Versandplan erneut abrufen: `selected_agents.versand.url` zeigt Port 8012.
Der Koordinator bleibt unverändert.

## Hinweise

- Frische Installation, MCP, HTTP-Ablauf und KI-Antwort erfolgreich getestet.
- HTTP 429: Kontingent erreicht; HTTP 503: Modell vorübergehend nicht verfügbar.
  Details im Proxy-Terminal prüfen. Kein automatischer Modell-Fallback.
- Modellverfügbarkeit und Kontingente hängen vom verwendeten Google-Projekt ab.
- Schlüssel nicht ins Repository schreiben. Master-Key schützt nur den LiteLLM-Zugang.
- Lokaler Demonstrationsbetrieb; Fachdienste besitzen keine Authentifizierung.
- Beenden: Chat mit `exit`, Server jeweils mit **Strg+C**.
