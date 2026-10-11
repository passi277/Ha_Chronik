# Chronik für Home Assistant

**Chronik** ist eine Custom Integration, die automatisch ein Tagebuch deines Gartens führt:
Regen, Bewässerung, Mähen, Pool-Rückspülen, Alarme und KI-Befunde werden als Termine in
Kalender eingetragen. So siehst du rückblickend auf einen Blick, was an welchem Tag passiert ist.

## Was erfasst wird

| Kalender | Quelle | Erkennung | Beispiel |
|---|---|---|---|
| 🌧️ Regen | Sensor mit Regenmenge (Tag/gesamt) | jeder Anstieg; Pause > Lücke (Std. 60 min) = neue Regenphase; Tages-Reset wird erkannt | `🌧️ Regen · 4,2 mm` |
| 💧 Bewässerung | pro Zone binary_sensor/switch/valve/input_boolean, optional Wasserzähler | an → aus = ein Lauf, Mindestdauer filtert Flackern | `💧 Haus · 18 min · 85 L` |
| 🌱 Mähen | `lawn_mower` | `mowing` → anderer Zustand; kurze Pausen werden zusammengefasst; `error` als eigener Eintrag | `🌱 Mähen · 1 h 20 min` |
| 🏊 Pool | Timer/Schalter während des Rückspülens und/oder Zähler, der danach zurückgesetzt wird | aktive Phase = Termin; Zähler-Reset wird an den Lauf angehängt | `🏊 Pool Rückspülen · 3 min · nach 41,5 h` |
| 🚨 Alarme | `alarm_control_panel` (ausgelöst), Sirenen, Binärsensoren | aktiv = Termin; optional Scharf/Unscharf | `🚨 Garten ausgelöst · 2 min` |
| 🤖 KI-Befunde | `input_text` / `sensor` / `text` mit KI-Ergebnis | jeder neue Text = Eintrag, Volltext in der Beschreibung | `🤖 Pool KI-Befund: Wasser klar` |
| 📅 Tagesbilanz | alle obigen | ganztägiger Eintrag mit Zusammenfassung und chronologischer Liste | `📅 🌧️ 4,2 mm · 💧 3× · 52 min · 🌱 1 h 20 min` |

Es wird nur für Kategorien mit konfigurierten Quellen ein Kalender angelegt.
In der Kalender-Ansicht kannst du Einträge außerdem **manuell anlegen, bearbeiten und löschen**
(z. B. „Dünger gestreut“).

Während ein Lauf aktiv ist, ist der Kalender `on` – das lässt sich auch als Trigger nutzen.

## Installation

1. HACS → ⋮ → *Benutzerdefinierte Repositories* → `https://github.com/passi277/ha_chronik`, Typ *Integration*.
2. „Chronik“ installieren und Home Assistant neu starten.
3. *Einstellungen → Geräte & Dienste → Integration hinzufügen → Chronik*.
4. Pro Kategorie die Quellen auswählen (alle Seiten optional). Später änderbar über *Konfigurieren*.

Manuell: Ordner `custom_components/chronik` nach `config/custom_components/` kopieren.

## Bilder zu KI-Befunden

Unter *KI-Befunde* lässt sich ein **Bildordner** angeben (z. B. `/media/llmvision/snapshots`).
Bilder, die dort kurz vor einem neuen Befund gespeichert wurden (Zeitfenster einstellbar, Standard 3 min),
werden automatisch an den Eintrag gehängt – ideal für LLM Vision mit `expose_images: true`.
Die Bilder werden dabei nach `/media/chronik` kopiert, weil LLM Vision Schnappschüsse ohne
Timeline-Eintrag wieder löscht. Die Kopien werden mit dem Eintrag (Aufbewahrungsdauer/Löschen) entfernt.
Die Karte zeigt sie als Vorschaubild in der Zeitleiste und als Galerie mit Vollbild im Detailfenster.
`chronik.backfill` hängt Bilder auch nachträglich an ältere Befunde – aber nur, solange die Originaldateien noch existieren.

## Services

### `chronik.add_entry`
Eintrag aus Automationen schreiben, z. B. eine LLM-Vision-Antwort:

```yaml
action: chronik.add_entry
data:
  category: ai
  title: "🤖 Rasen: {{ response.response_text[:60] }}"
  description: "{{ response.response_text }}"
```

Optional: `start`, `end` (Standard: jetzt, Punkt-Eintrag), `data` (beliebige Zusatzwerte),
`images` (Bildpfade, z. B. `/media/llmvision/snapshots/x.jpg` oder `/local/x.jpg`).
Antwort: `uid` des Eintrags.

### `chronik.backfill`
Rekonstruiert Einträge aus dem Recorder-Verlauf, z. B. direkt nach der Installation:

```yaml
action: chronik.backfill
data:
  days: 10
```

Die Reichweite ist durch `recorder: purge_keep_days` begrenzt (Standard 10 Tage).
Mehrfaches Ausführen erzeugt keine Duplikate; live erfasste oder manuell bearbeitete
Einträge werden nicht überschrieben.

### `chronik.delete_entry`
Löscht einen Eintrag per `uid`.

## Dashboard-Karte

Die Integration bringt eine eigene Karte mit. Sie wird unter `/chronik/chronik-card.js` ausgeliefert und
beim Start automatisch als Dashboard-Ressource eingetragen bzw. aktualisiert (Storage-Modus):

```yaml
type: custom:chronik-card
days: 7              # 7 oder 30 (umschaltbar in der Karte)
# title: Chronik
# categories: [rain, irrigation, mowing]   # nur bestimmte Kategorien
# show_stats: true   # Kennzahlen-Kacheln
# show_week: true    # Wochenstreifen mit Regenbalken
# show_filters: true # Filter-Chips
# limit: 25          # Einträge pro „mehr anzeigen“
# animations: full   # full | reduced | off
```

Zeigt die Karte „Konfigurationsfehler“, wurde der Kartencode noch nicht geladen: App/Seite neu laden
(Companion-App: *Frontend-Cache zurücksetzen*). Fehlt die Kartendatei, steht ein Fehler im Log;
in den Diagnosedaten der Integration steht unter `card`, ob die Datei vorhanden ist und ausgeliefert wird.

Kennzahlen und Tage im Wochenstreifen sind antippbar und filtern die Zeitleiste;
ein Eintrag öffnet die Detailansicht. Laufende Vorgänge erscheinen oben als Banner.

Alternativ funktioniert die eingebaute Kalenderkarte:

```yaml
type: calendar
initial_view: listWeek
entities:
  - entity: calendar.chronik_tagesbilanz
  - entity: calendar.chronik_regen
  - entity: calendar.chronik_bewasserung
  - entity: calendar.chronik_mahen
  - entity: calendar.chronik_pool
  - entity: calendar.chronik_alarme
  - entity: calendar.chronik_ki_befunde
```

(Die Entity-IDs hängen vom Namen der Chronik und der Systemsprache ab.)

## Speicherung

Einträge liegen in `.storage/chronik.<entry_id>` und werden nach der eingestellten
Aufbewahrungsdauer (Standard 3 Jahre, 0 = unbegrenzt) gelöscht – unabhängig vom Recorder.

## Entwicklung

```bash
pip install -r requirements_test.txt ruff
ruff check custom_components tests
pytest
```

Die Detektoren (`custom_components/chronik/detectors/`) sind reine Zustandsautomaten ohne
Home-Assistant-Abhängigkeit; derselbe Code verarbeitet Live-Zustände und den Recorder-Verlauf.
