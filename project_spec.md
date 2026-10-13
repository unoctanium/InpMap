# Projektbriefing: Cross-Platform Input Remapper – Linux V1

> **Änderung 2026-10-13:** Die InpMap-Konfigurationssprache (Dateiendung `.inpmap`, Spezifikation in `docs/configuration.md`, ursprünglich `docs/dsl.md`) ersetzt JSON als einziges Konfigurationsformat. JSON-Konfigurationsdateien werden nicht mehr unterstützt. Die Arbeitsschritte in §11 und §14 sowie der JSON-Entwurf in §7 sind historisch und beschreiben den ursprünglichen Weg.

## 1. Rolle und Arbeitsweise

Du bist mein technischer Projektpartner und leitender Softwareentwickler für die Entwicklung eines eigenen Input Remappers.

Deine Aufgaben:
- Entwickle die Software in kleinen, überprüfbaren Schritten.
- Erzeuge tatsächlich ausführbaren Code, nicht nur Architekturvorschläge oder Pseudocode.
- Erkläre knapp, welche Dateien anzulegen oder zu ändern sind und welche Befehle ich auf meinem System ausführen soll.
- Unterstütze mich beim Testen, der Fehlersuche und der schrittweisen Erweiterung.
- Analysiere Fehlermeldungen und tatsächliche Testergebnisse, bevor du Lösungen vorschlägst.
- Erfinde keine Testergebnisse und behaupte niemals, Code sei getestet worden, wenn er nicht ausgeführt wurde.
- Vermeide unnötige Rückfragen, wenn eine vernünftige technische Entscheidung möglich ist. Dokumentiere getroffene Annahmen.
- Liefere bei jeder Implementierungsstufe einen klaren Abschlusszustand und konkrete nächste Schritte.

**Arbeitsprinzip:** Beginne nach der Analyse des Projektbriefings mit der Implementierung. Wir wollen möglichst schnell einen minimalen, real funktionierenden Prototypen erstellen und auf meinem Rechner testen. Entwickle nicht zuerst ein umfangreiches theoretisches Konzept und verschiebe die Implementierung auf später.

Wenn du in einer Umgebung mit Terminal-, Datei- oder Repository-Zugriff arbeitest, nutze diese Möglichkeiten, um Dateien anzulegen, Tests auszuführen und Ergebnisse zu prüfen. Andernfalls liefere vollständige Dateiinhalte und genaue Shell-Befehle, die ich lokal ausführen kann.

## 2. Projektziel

Wir entwickeln einen eigenen, konfigurationsbasierten Input Remapper mit einer plattformübergreifend konzipierten Mapping- und Makro-Engine.

Als funktionale Referenz dient das Open-Source-Projekt **Input Remapper von Sezanteb**:

https://github.com/sezanzeb/input-remapper

Input Remapper dient als Referenz für:
- Erkennung und Verarbeitung von Eingabegeräten
- Mapping-Regeln
- Press-/Release-Semantik
- Makros und deren Ausführungsmodell
- Modifier, Bedingungen und Variablen
- Umgang mit virtuellen Eingabegeräten

Wir wollen die relevanten Dokumentations- und Quellcodebereiche untersuchen und daraus eine eigene technische Spezifikation ableiten.

Wir wollen nicht einfach eine GUI nachbauen. Unser Ziel ist ein schlanker, zunächst GUI-loser Remapper, dessen Regeln vollständig in einer Konfigurationsdatei (InpMap-Konfigurationssprache, `.inpmap`) definiert werden.

Der entscheidende funktionale Unterschied: **Eine einzelne Eingabe kann mehrere Aktionen auf unterschiedlichen virtuellen Geräten auslösen.** Beispielsweise kann ein Tastendruck gleichzeitig eine andere Taste auf einer virtuellen Tastatur und einen Button auf einem virtuellen Gamepad aktivieren.

Spätere Versionen sollen komplexe Makros und weitere Eingabegeräte unterstützen. Deshalb muss die Architektur Erweiterungen ermöglichen, ohne den gesamten Code neu schreiben zu müssen.

## 3. Zielsystem und technische Rahmenbedingungen

### Entwicklungssystem

- Betriebssystem: CachyOS Linux
- Distributionstyp: Arch Linux-basiert
- Desktop: KDE Plasma unter Wayland
- Ziel für V1: ausschließlich Linux
- Hardware: physische Tastatur und Gamecontroller
- Analoge Eingaben sind in V1 ausdrücklich ausgeschlossen.

### Programmiersprache und Technologien

- Python 3
- die InpMap-Konfigurationssprache (`.inpmap`, `docs/configuration.md`) als einziges Konfigurationsformat für Mapping-Regeln (ursprünglich JSON)
- `evdev` zum Lesen physischer Eingabeereignisse
- `uinput` zum Erzeugen virtueller Eingabegeräte
- `pytest` für automatisierte Tests
- `argparse` oder eine vergleichbar schlanke Lösung für die CLI
- `venv` und `pip` für die Python-Entwicklungsumgebung, sofern sinnvoll

Verwende zunächst möglichst wenige Abhängigkeiten.

Die Mapping-Engine soll möglichst unabhängig vom Linux-Backend bleiben. Plattformabhängige Funktionen für Eingabeerkennung und Geräteausgabe werden hinter klaren Schnittstellen gekapselt.

Wir müssen die tatsächliche Kompatibilität der gewählten Bibliotheksversionen und APIs überprüfen. Behaupte nicht, dass bestimmte Methoden existieren, ohne dies anhand der installierten Bibliothek oder ihrer Dokumentation zu verifizieren.

## 4. Langfristige Produkt-Roadmap

Die folgenden Meilensteine definieren die beabsichtigte Produktentwicklung.

### V1 – Linux, ohne GUI

- Physische Tastatur und digitale Gamepad-Buttons lesen.
- Eingaben erkennen und eindeutig identifizieren.
- Mapping-Regeln aus der Konfigurationsdatei laden und validieren.
- Regeln auf Eingaben anwenden.
- Virtuelle Tastatur und virtuellen Gamecontroller erzeugen.
- Ausgaben an mehrere virtuelle Geräte verteilen.
- Press und Release korrekt verarbeiten.
- Gemappte Originaleingaben unterdrücken.
- Konfigurationsfehler und Laufzeitprobleme protokollieren.
- CLI für Start, Konfigurationsprüfung und Diagnose bereitstellen.
- Die Architektur so anlegen, dass der Remapper später als Hintergrunddienst (Daemon) laufen kann.

Keine GUI. Keine analogen Sticks. Keine Mausbewegungen. Die Makro-Engine bleibt zunächst minimal.

### V1.1 – Makro- und Mapping-Erweiterung

Auf Basis der Dokumentation und des Quellcodes von Input Remapper entwickeln wir eine erweiterte Mapping- und Makro-Engine.

Geplante Funktionen:
- `press` und `release`
- `hold`
- Modifier wie Shift, Ctrl und Alt
- `wait` mit Zeitangabe
- Sequenzen von Aktionen
- parallele Aktionen
- Bedingungen
- Variablen und Zustandsverwaltung
- Abbruch und saubere Freigabe aktiver Ausgaben
- mehrere virtuelle Ausgabegeräte pro Regel

Definiere die Semantik dieser Funktionen anhand einer dokumentierten Spezifikation. Vermeide, eine Makrosprache nur anhand ihrer Namen nachzuahmen.

### V2 – Windows, ohne GUI

- Windows-spezifische Eingabeerkennung und Ausgabe implementieren.
- Mapping-Engine, Konfigurationssprache und Konfigurationsmodell soweit möglich wiederverwenden.
- Geeignete Lösungen für virtuelle Tastatur- und Gamepad-Geräte untersuchen.
- Treiberanforderungen, Berechtigungen und Installation dokumentieren.

Beachte: `evdev` und `uinput` sind Linux-spezifisch. Sie dürfen nicht direkt in die plattformunabhängige Engine eingebaut werden.

### V3 – Windows mit GUI

- Grafische Konfiguration
- Geräteauswahl
- Mapping-Editor
- Makro-Editor
- Statusanzeige und Diagnose
- Profile verwalten

### V4 – Linux mit GUI

- Linux-GUI auf Basis der gemeinsamen Mapping-Engine
- Integration in Linux-Desktopumgebungen
- Geräteverwaltung und Berechtigungsmanagement
- Konfigurations- und Diagnosefunktionen

## 5. Spätere Ausführung als Daemon

Der Remapper soll später als Hintergrunddienst laufen können, ohne dass ein Terminalfenster geöffnet bleiben muss. Plane diese Betriebsart bereits bei der Architektur, implementiere sie aber erst, wenn der grundlegende Ende-zu-Ende-Test stabil funktioniert.

Anforderungen an die spätere Daemon-Ausführung:
- Starten, Stoppen und Neustarten über `systemd`.
- Konfiguration aus einer definierten `.inpmap`-Datei laden.
- Logs über `journald` oder einen klar definierten Logging-Mechanismus bereitstellen.
- Beim Start Geräte erkennen und beim Gerätewechsel angemessen reagieren.
- Fehler und Neustarts nachvollziehbar protokollieren.
- Beim Beenden aktive virtuelle Ausgaben freigeben und Geräte sauber schließen.
- Keine GUI-Abhängigkeit und keine interaktive Terminal-Eingabe voraussetzen.
- Berechtigungen für physische Eingabegeräte und `/dev/uinput` möglichst restriktiv und nachvollziehbar konfigurieren.
- Einen sinnvollen Weg zum Neuladen der Konfiguration vorsehen, beispielsweise über ein Signal oder später eine lokale IPC-Schnittstelle. Nicht unnötig früh ein komplexes Steuerprotokoll bauen.

Trenne dafür die eigentliche Remapping-Laufzeit von der CLI-Steuerung. Die Kernlogik darf nicht davon abhängen, dass ein interaktives Terminal vorhanden ist. Für V1 reicht zunächst ein foreground-Modus mit sauberem Shutdown; dieser erleichtert Tests und Debugging. Der spätere systemd-Dienst kann denselben Laufzeitcode verwenden.

## 6. Verbindliche V1-Funktionalität

V1 soll sich auf einen klaren Ende-zu-Ende-Test konzentrieren.

### Eingaben

- Physische Tastatur
- Digitale Buttons eines Gamecontrollers
- Press- und Release-Ereignisse

Nicht enthalten:
- Analogsticks
- Triggerachsen
- Mausbewegungen
- Makros mit komplexen Bedingungen

### Ausgaben

Erzeuge mindestens zwei virtuelle Geräte:

1. Eine virtuelle Tastatur
2. Einen virtuellen Gamecontroller

Linux und geeignete Testprogramme müssen beide Geräte erkennen und ihre Eingaben empfangen können.

Eine Regel darf Aktionen auf mehreren virtuellen Geräten auslösen.

### Eingabeunterdrückung

Wenn eine physische Eingabe durch eine aktive Mapping-Regel ersetzt wird, darf die ursprüngliche Eingabe nicht zusätzlich bei der Zielanwendung ankommen.

Unmapped Eingaben sollen entsprechend der definierten Durchreichungsstrategie unverändert bleiben.

Untersuche ausdrücklich, wie das unter Linux funktioniert. `evdev` allein unterdrückt keine Eingaben. Prüfe die dafür notwendigen Mechanismen, insbesondere exklusives Öffnen von Eingabegeräten über `EVIOCGRAB`, dessen Auswirkungen und mögliche Konflikte mit dem Desktop oder anderen Anwendungen.

Dokumentiere, welche Geräte abgefangen werden und wie sie bei Programmende oder Fehlern freigegeben werden.

### Zustandsverwaltung

Die Software muss mindestens unterscheiden zwischen:
- Eingabe gedrückt
- Eingabe losgelassen
- Ausgabe aktiv
- Ausgabe freigegeben

Wichtig: Werden mehrere Eingaben auf dieselbe virtuelle Taste abgebildet, darf das Loslassen einer Eingabe eine andere weiterhin aktive Eingabe nicht versehentlich freigeben.

Beispiel: Zwei physische Buttons aktivieren beide die virtuelle Taste `KEY_Y`. Solange mindestens einer der beiden Buttons gehalten wird, muss die virtuelle Taste aktiv bleiben.

Alle aktiven Ausgaben müssen bei Programmende, Geräteverlust und Fehlern nach Möglichkeit zuverlässig freigegeben werden.

## 7. Erster verbindlicher Ende-zu-Ende-Test

Dies ist das wichtigste Abnahmekriterium für den ersten Prototypen.

### Sollverhalten

Ich drücke `X` auf meiner physischen Tastatur.

Daraufhin:
- wird `X` abgefangen und nicht zusätzlich durchgereicht;
- meldet die virtuelle Tastatur `Y` als gedrückt;
- meldet der virtuelle Gamecontroller den Facebutton `A` als gedrückt.

Ich lasse `X` los.

Daraufhin:
- meldet die virtuelle Tastatur `Y` als losgelassen;
- meldet der virtuelle Gamecontroller den Facebutton `A` als losgelassen;
- bleibt kein virtueller Button hängen.

Verwende für den Gamecontroller zunächst `BTN_SOUTH`, sofern das für den gewählten virtuellen Gerätetyp passt. Prüfe, wie der verwendete Linux-Input-Stack diesen Button interpretiert. Die Zuordnung zu A/B/X/Y hängt von der jeweiligen Controller-Konvention ab.

Verwende zunächst eine eindeutige Tastenidentifikation. Berücksichtige, dass Linux-Keycodes und Zeichen auf Tastaturlayouts nicht dasselbe sind. Die erste Implementierung darf `KEY_Y` als Linux-Keycode ausgeben; eine weitergehende layoutbewusste Zeichenausgabe muss separat spezifiziert werden.

### Vorgeschlagene JSON-Konfiguration (historisch)

Historisch: JSON wurde durch die Konfigurationssprache ersetzt; dasselbe Mapping lautet heute `map KEY_X { hold KEY_Y; hold BTN_SOUTH }` (siehe `config/example.inpmap`).

Das folgende Format ist ein erster Entwurf. Prüfe und verbessere es bei Bedarf, bevor du es verbindlich implementierst.

```json
{
  "version": 1,
  "devices": {
    "keyboard": {
      "type": "keyboard"
    },
    "gamepad": {
      "type": "gamepad"
    }
  },
  "mappings": [
    {
      "id": "keyboard-x-to-y-and-gamepad-a",
      "input": {
        "device": "physical-keyboard",
        "type": "key",
        "code": "KEY_X"
      },
      "consume": true,
      "outputs": [
        {
          "device": "keyboard",
          "type": "key",
          "code": "KEY_Y"
        },
        {
          "device": "gamepad",
          "type": "button",
          "code": "BTN_SOUTH"
        }
      ]
    }
  ]
}
```

Die Konfiguration muss validiert werden; Fehler werden mit Position (`DATEI:ZEILE:SPALTE`) gemeldet. Ungültige Gerätereferenzen, unbekannte Event-Typen und ungültige Event-Codes müssen mit verständlichen Fehlermeldungen abgewiesen werden.

Die Konfiguration muss nicht von Anfang an alle späteren Makrofunktionen enthalten. Sie muss aber so gestaltet sein, dass wir später Makroaktionen ergänzen können, ohne das Format vollständig zu ersetzen.

## 8. Architekturvorschlag

Beginne mit einer kleinen, modularen Projektstruktur:

```text
input-remapper-next/
├── pyproject.toml
├── README.md
├── config/
│   └── example.inpmap
├── src/
│   └── remapper/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── models.py
│       ├── input_reader.py
│       ├── mapping_engine.py
│       ├── output_manager.py
│       ├── state_manager.py
│       └── backends/
│           ├── __init__.py
│           └── linux.py
└── tests/
    ├── test_config.py
    ├── test_mapping.py
    ├── test_state.py
    └── test_multi_output.py
```

Passe die Struktur an, falls sich im Laufe der Implementierung eine einfachere Lösung ergibt. Erzeuge keine leeren Module ohne Zweck.

### Verantwortlichkeiten

`cli.py`
- Kommandozeilenargumente
- Start und kontrollierter Stopp
- Konfigurationsprüfung und Diagnose

`config.py`
- Konfigurationsdatei parsen und übersetzen
- Schema und Referenzen validieren
- verständliche Fehler melden

`models.py`
- Datenstrukturen für Eingaben, Regeln und Aktionen

`input_reader.py`
- physische Linux-Eingabegeräte erkennen
- Events auslesen
- Geräteverlust behandeln

`mapping_engine.py`
- Eingaben den passenden Regeln zuordnen
- Regeln auflösen
- Aktionen an den Output-Manager übergeben

`output_manager.py`
- virtuelle Geräte verwalten
- Events an die richtigen virtuellen Geräte senden

`state_manager.py`
- aktive Eingaben und Ausgaben verfolgen
- Press-/Release-Semantik gewährleisten
- konkurrierende Mappings korrekt behandeln

`backends/linux.py`
- Linux-spezifische APIs und Ressourcen kapseln

Die Kernlogik soll nicht direkt von `evdev`-Objekten abhängen. Verwende bei Bedarf einfache interne Event-Datenstrukturen, damit die Mapping-Logik später auch mit einem Windows-Backend getestet werden kann.

## 9. Tests und Qualitätssicherung

Schreibe Tests frühzeitig. Verwende für die Kernlogik möglichst Unit-Tests ohne Root-Rechte und ohne physische Hardware.

### Automatisierte Tests

1. Gültige Konfiguration wird akzeptiert.
2. Fehlerhafte Konfigurationen werden abgewiesen.
3. Eine Eingabe aktiviert genau die konfigurierten Ausgaben.
4. Mehrere Ausgaben auf verschiedenen virtuellen Geräten funktionieren.
5. Press und Release werden korrekt verarbeitet.
6. Doppelte oder überlappende Mappings verursachen keine verfrühte Freigabe.
7. Unmapped Eingaben werden gemäß der festgelegten Strategie behandelt.
8. Fehler und Abbrüche führen nicht zu dauerhaft aktiven virtuellen Tasten.
9. Geräteverlust wird kontrolliert behandelt.
10. Die Mapping-Engine ist unabhängig von konkreten Linux-Geräteobjekten testbar.

### Integrationstests

Auf dem realen CachyOS-System prüfen wir anschließend:
- Erzeugung der virtuellen Tastatur
- Erzeugung des virtuellen Gamecontrollers
- Erkennung durch `evtest` oder vergleichbare Linux-Werkzeuge
- Ende-zu-Ende-Test mit physischem `X`
- tatsächliche Unterdrückung des ursprünglichen `X`
- korrekte Freigabe beider Ausgaben

Unterscheide stets zwischen Unit-Tests, simulierten Tests und realen Hardwaretests.

## 10. Sicherheit und Systemintegration

Da die Anwendung Eingabegeräte abfängt und virtuelle Eingaben erzeugt, müssen wir Berechtigungen und Fehlerbehandlung ernst nehmen.

- Vermeide unnötige Ausführung des gesamten Programms als Root.
- Prüfe die erforderlichen Berechtigungen für `/dev/input/event*` und `/dev/uinput`.
- Dokumentiere die Einrichtung für CachyOS/Arch Linux.
- Verwende keine pauschalen, unsicheren Berechtigungsänderungen für alle Eingabegeräte.
- Stelle sicher, dass das Programm Geräte beim normalen Beenden freigibt.
- Implementiere einen sicheren Abbruchpfad.
- Verhindere, dass ein ungültiges Mapping unkontrolliert Tastatureingaben erzeugt.
- Gib ausreichend Diagnoseinformationen aus, ohne unnötig Eingabeinhalte zu protokollieren.

Prüfe außerdem, wie sich exklusives Abfangen auf KDE, Desktop-Shortcuts, andere Remapper und laufende Anwendungen auswirkt. Die Software darf nicht voraussetzen, dass jedes Eingabegerät konfliktfrei exklusiv geöffnet werden kann.

## 11. Entwicklungsablauf

Arbeite in dieser Reihenfolge:

### Schritt 1 – Umgebung prüfen

- Python-Version ermitteln
- Installierte oder verfügbare `evdev`-Version prüfen
- Zugriff auf Eingabegeräte und `/dev/uinput` untersuchen
- passende Werkzeuge wie `evtest` prüfen
- Abhängigkeiten möglichst minimal halten

Erstelle keine Änderungen am System, bevor die notwendigen Schritte klar sind.

### Schritt 2 – Projektgerüst und JSON-Validierung

- Projektdateien erzeugen
- virtuelle Python-Umgebung einrichten
- Konfiguration laden und validieren
- erste automatisierte Tests ausführen

### Schritt 3 – Virtuelle Geräte

- virtuelle Tastatur erzeugen
- virtuellen Gamecontroller erzeugen
- einzelne Testevents ausgeben
- Erkennung durch Linux verifizieren

### Schritt 4 – Mapping-Engine

- interne Event-Datenstrukturen
- Eingabe-Regelzuordnung
- mehrere Ausgabeaktionen
- Press-/Release-Zustände

### Schritt 5 – Physische Eingaben

- physische Tastatur lesen
- digitale Gamepad-Buttons lesen
- Gerätereferenzen und Geräteauswahl definieren
- Unterdrückung gemappter Originaleingaben implementieren

### Schritt 6 – Ende-zu-Ende-Test

Die oben beschriebene Abbildung von physischem `X` auf virtuelles `Y` plus Gamepad-Button `A` implementieren und praktisch prüfen.

### Schritt 7 – Robustheit

- Fehlerbehandlung
- Gerätekonnektivität
- sichere Freigabe
- Diagnose
- zusätzliche Tests

### Schritt 8 – Makro-Spezifikation

Erst nach einem erfolgreichen V1-Test:
- relevante Dokumentation von Input Remapper untersuchen
- Makro-Implementierung und Tests analysieren
- bestehende Semantik dokumentieren
- eigenes JSON-Aktionsmodell entwerfen
- schrittweise implementieren

### Schritt 9 – Daemon-Betrieb

Erst nachdem der foreground-Modus zuverlässig funktioniert:
- Laufzeitcode und CLI-Steuerung sauber trennen
- systemd-Unit für den Dienst entwerfen
- Start, Stop, Restart und Logs testen
- Verhalten bei Geräteverlust und Konfigurationsfehlern testen
- sichere Berechtigungen und Shutdown-Verhalten verifizieren

Der Daemon soll denselben getesteten Runtime-Code verwenden wie der foreground-Modus. Vermeide zwei getrennte Implementierungen der Mapping-Logik.

## 12. Regeln für die Zusammenarbeit

Bitte beachte bei jeder Antwort:

1. Liefere bei Implementierungsaufgaben vollständige, verwendbare Dateien oder klar abgegrenzte Änderungen.
2. Nenne immer den Dateipfad.
3. Gib ausführbare Befehle für Installation, Start und Tests an.
4. Verwende keine erfundenen APIs, Event-Codes oder Bibliotheksfunktionen.
5. Prüfe relevante Dokumentation, wenn Web- oder Repository-Zugriff verfügbar ist.
6. Vermeide es, denselben Code in mehreren Dateien unnötig zu duplizieren.
7. Halte den ersten Prototyp klein.
8. Führe Tests nach jeder relevanten Änderung aus, wenn du über eine passende Umgebung verfügst.
9. Wenn du einen Test nicht ausführen kannst, sage es ausdrücklich.
10. Bei einem Fehler analysiere zunächst die konkrete Fehlermeldung und den betroffenen Code.
11. Frage mich nach tatsächlichen Testergebnissen, wenn sie für den nächsten Schritt benötigt werden.
12. Warte nach größeren, hardwareabhängigen Schritten auf mein Testergebnis, bevor du darauf aufbauende Änderungen voraussetzt.

## 13. Definition of Done für den ersten Prototyp

Der erste Prototyp gilt als erfolgreich, wenn:

- die Konfiguration validiert wird (ursprünglich JSON, heute `.inpmap`);
- die virtuelle Tastatur und der virtuelle Gamecontroller von Linux erkannt werden;
- physisches `X` die virtuelle Taste `KEY_Y` und den Gamepad-Button `BTN_SOUTH` aktiviert;
- beide virtuellen Ausgaben beim Loslassen von `X` wieder freigegeben werden;
- das ursprüngliche `X` bei aktivem Mapping nicht zusätzlich an die Zielanwendung durchgereicht wird;
- die Kernlogik automatisierte Tests besteht;
- der Prozess ohne dauerhaft aktive virtuelle Tasten beendet werden kann;
- der Remapper im Vordergrundmodus zuverlässig läuft und sich später ohne grundlegende Architekturänderung als systemd-Daemon betreiben lässt;
- die Installation und der Test in einer README nachvollziehbar dokumentiert sind.

## 14. Beginne jetzt mit der Implementierung

Analysiere zunächst die Anforderungen und beginne dann direkt mit **Schritt 1 und Schritt 2**.

Wenn du Terminal- und Dateizugriff hast:
- prüfe die lokale Umgebung;
- erstelle das Projektgerüst;
- implementiere JSON-Validierung und erste Unit-Tests;
- führe die Tests aus;
- berichte konkrete Ergebnisse.

Wenn du keinen lokalen Dateizugriff hast:
- liefere die erste vollständige, lauffähige Dateigruppe;
- gib die Shell-Befehle zum Erstellen und Testen an;
- beginne mit der JSON-Validierung und den Kernmodellen.

Bitte liefere keine weitere allgemeine Projektbeschreibung. Wir haben die Anforderungen bereits definiert. **Beginne mit konkretem Code und führe uns iterativ zu einem funktionierenden Linux-Prototypen.**
