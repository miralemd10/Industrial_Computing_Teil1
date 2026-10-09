# Industrial_Computing_Teil1

Industrial Computing, Homework Part 1, Technical Track: Ein deutschsprachiger
Lager-Assistent für einen Socken-Onlineshop. Der LangChain-Agent verwendet
ein Sprachmodell über einen lokalen LiteLLM-Proxy und drei MCP-Tools:

- `get_inventory_and_orders`: liest Lagerbestände und offene sowie versendete
  Bestellungen aus SQLite. Der freie Bestand ist der physische Bestand minus
  offene Bestellmengen; negative Werte zeigen einen Fehlbestand. Mengen sind
  Paar Socken. Stückpreise werden von diesem Tool nicht ausgegeben.
- `calculate_bulk_discount`: berechnet den Mengenrabatt und den Endbetrag in Euro.
- `append_audit_event`: hängt eine Beschreibung mit UTC-Zeitstempel an das
  Audit-Protokoll an. Der Agent gibt dieses Tool nur bei einer ausdrücklichen
  Protokollierungsbitte in der aktuellen Nachricht frei.

## Voraussetzungen und Installation

Benötigt werden Python (die vorhandene lokale Umgebung verwendet 3.12),
PowerShell und Internetzugang für die Paketinstallation und den Modellzugriff.
Für den Agenten ist ein Gemini-API-Schlüssel mit Zugriff auf das in
`litellm_config.yaml` konfigurierte Modell erforderlich.

Alle PowerShell-Befehle im Ordner `Teil 1` ausführen. Nach dem Klonen
zuerst vom Repository-Hauptverzeichnis in diesen Ordner wechseln:

```powershell
cd ".\Teil 1"
```

Die Befehle verwenden die Interpreter der virtuellen Umgebungen direkt:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt

python -m venv .venv-litellm
.\.venv-litellm\Scripts\python.exe -m pip install "litellm[proxy]"
```

`requirements.txt` enthält MCP, LangChain, den OpenAI-kompatiblen Modellclient
und den MCP-Adapter, aber kein LiteLLM. Die separate Proxy-Umgebung vermeidet
einen Versionskonflikt: Das Projekt verlangt `mcp>=1.12,<2`, der lokal
installierte LiteLLM-Proxy 1.104.0 dagegen `mcp>=2.2.0,<3`.
SQLite ist Teil von Python.

## Datenbank und Agent starten

Zuerst die Beispieldatenbank initialisieren:

```powershell
.\.venv\Scripts\python.exe .\init_db.py
```

**Terminal 1: LiteLLM.** Die Platzhalter durch eigene Schlüssel ersetzen:
`GEMINI_API_KEY` ist der Zugang zum Modellanbieter. `LITELLM_MASTER_KEY` ist
ein selbst gewählter Schlüssel für den lokalen Proxy, den auch der Agent
verwenden muss. Die Variablen gelten nur für das jeweilige Terminal.

```powershell
$env:GEMINI_API_KEY = "DEIN_GEMINI_API_SCHLUESSEL"
$env:LITELLM_MASTER_KEY = "sk-DEIN_LOKALER_PROXY_SCHLUESSEL"
.\.venv-litellm\Scripts\litellm.exe --config .\litellm_config.yaml --host 127.0.0.1 --port 4000
```

Dieses Terminal geöffnet lassen. Die Konfiguration ordnet den Modellnamen
`lager_assistent` dem Modell `gemini/gemini-3.8-flash` zu und liest
`GEMINI_API_KEY` aus der Umgebung.

**Terminal 2: Agent.** Sobald der Proxy bereit ist, im Repository-Verzeichnis
denselben Proxy-Schlüssel setzen und den Agenten starten:

```powershell
$env:LITELLM_MASTER_KEY = "sk-DEIN_LOKALER_PROXY_SCHLUESSEL"
.\.venv\Scripts\python.exe .\agent.py
```

Der Agent verbindet sich mit `http://127.0.0.1:4000/v1` und startet
`mcp_server.py` selbst als stdio-Unterprozess mit seinem Python-Interpreter.
Ein separates MCP-Terminal ist nicht nötig. Die Unterhaltung endet mit `exit`;
den Proxy mit `Strg+C` beenden.

## Lokaler Test ohne Modell-API-Key

`test_mcp_client.py` habe ich zur eigenen Überprüfung der MCP-Tools erstellt.
Nach der Datenbankinitialisierung prüft der Test Lagerdaten, Rabattberechnung
und Audit-Protokollierung ohne Modell-API-Key oder laufenden LiteLLM-Proxy:

```powershell
.\.venv\Scripts\python.exe .\test_mcp_client.py
```

Dabei wird ein Testeintrag an `logs/audit.jsonl` angehängt.
Die Lagerdatenbank bleibt unverändert.

## Beispielfragen

1. „Wie viele offene und versendete Bestellungen gibt es, und wie viele Paar
   Socken sind je Produkt physisch vorhanden, offen bestellt und frei verfügbar?“
2. „Was kosten 50 Paar Socken zu je 12.50 Euro nach Mengenrabatt?
   Nenne Ausgangsbetrag, Rabatt und Endbetrag.“
3. „Bitte erstelle einen Audit-Eintrag mit der Beschreibung:
   Lagerbestand und Mengenrabatt wurden geprüft.“

## Mengenrabatt-Tool

Das MCP-Tool `calculate_bulk_discount` nimmt eine positive Stückzahl und
`unit_price_euros` entgegen. Der Preis kann als JSON-Zahl oder Dezimalstring
angegeben werden, zum Beispiel `12.50` Euro. Er darf nicht negativ sein und
höchstens zwei Nachkommastellen haben. Rabattstaffeln: unter 10 Stück 0 %,
ab 10 Stück 5 %, ab 50 Stück 10 % und ab 100 Stück 15 %. Der Rabatt gilt für
die gesamte Menge und wird auf Cent mit `ROUND_HALF_UP` gerundet. Eurobeträge
werden als Dezimalstrings mit genau zwei Nachkommastellen ausgegeben.

Beispielaufruf:

```json
{"quantity": 10, "unit_price_euros": 12.50}
```

Ergebnis:

```json
{
  "quantity": 10,
  "discount_percent": 5,
  "amount_before_discount_euros": "125.00",
  "discount_amount_euros": "6.25",
  "final_amount_euros": "118.75"
}
```

Preise in der SQLite-Datenbank bleiben in Cent. Vor dem Aufruf des
Rabatt-Tools muss ein Centpreis durch 100 in Euro umgerechnet werden.

## Datenbank und Audit-Protokoll

`init_db.py` erzeugt `data/lager.db` samt Verzeichnis und den Tabellen
`products`, `orders` und `order_items`. Es legt vier Beispielprodukte und fünf
Bestellungen an, davon drei offen und zwei versendet. Erneutes Ausführen
ergänzt fehlende Beispiel-IDs, ohne vorhandene Datensätze zu ersetzen.

`logs/audit.jsonl` und das Verzeichnis `logs` entstehen beim ersten gültigen
Aufruf von `append_audit_event`. Jeder Aufruf ergänzt eine JSONL-Zeile mit
`timestamp` (UTC, ISO 8601 mit Millisekunden) und `description`; bestehende
Einträge bleiben erhalten. Datenbank- und Audit-Pfade beziehen sich immer auf
das Verzeichnis der Python-Dateien, unabhängig vom Arbeitsverzeichnis.
