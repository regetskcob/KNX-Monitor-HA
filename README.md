# KNX Monitor for Home Assistant

Integration for the [KNX Monitor add-on](https://github.com/regetskcob/KNX-Monitor): the add-on becomes the device "KNX Monitor" with sensors, a switch, device triggers, services, diagnostics and repairs, no MQTT broker needed.

## Requirements

- Home Assistant with Supervisor (Home Assistant OS or Supervised), 2025.1 or newer
- KNX Monitor add-on 1.9.7 or newer

## Installation

1. In HACS, add `https://github.com/regetskcob/KNX-Monitor-HA` as a *custom repository* of type *Integration* and install **KNX Monitor**.
2. Restart Home Assistant.
3. With the add-on running, Home Assistant shows "New device found: KNX Monitor". Confirm, done.

Without the add-on running the integration cannot be set up: the add-on hands over address and access itself.

## What it adds

- **Sensors:** bus connected, telegrams per minute and today, repeats, bus load, open alarms, last alarm, availability over 24 hours, history size, free space, low space.
- **Switch:** continuous recording on and off.
- **Device triggers:** watcher fired, alarm or fault on and off, bus connection lost and back.
- **Services:** `knx_monitor.create_report` creates the installation report, `knx_monitor.export_history` saves the history as an ETS group monitor file in the `knx_monitor` folder of the configuration (up to 31 days, or everything as a zip, at most 500 MB, one export at a time). Both are for administrators only.
- **Diagnostics** download on the device page, without names, addresses or values.
- **Repairs** when the bus has been disconnected for more than 10 minutes or recording paused because the disk is full.

While the integration is set up, the add-on stops announcing the same entities over MQTT. Remove the integration and the MQTT device comes back.

## Feedback

Bugs and wishes at [regetskcob/KNX-Monitor/issues](https://github.com/regetskcob/KNX-Monitor/issues).

This repository is generated from the development repository; please open an issue instead of a pull request.

License: GPLv3, like KNX Monitor.

---

<details>
<summary>🇩🇪 Deutsch</summary>

# KNX Monitor für Home Assistant

Integration für das [KNX-Monitor-Add-on](https://github.com/regetskcob/KNX-Monitor): Das Add-on wird zum Gerät „KNX Monitor“ mit Sensoren, Schalter, Geräte-Auslösern, Diensten, Diagnose und Reparaturhinweisen, ganz ohne MQTT-Broker.

## Voraussetzungen

- Home Assistant mit Supervisor (Home Assistant OS oder Supervised), ab 2025.1
- KNX-Monitor-Add-on ab 1.9.7

## Installation

1. In HACS unter *Benutzerdefinierte Repositories* `https://github.com/regetskcob/KNX-Monitor-HA` als *Integration* hinzufügen und **KNX Monitor** installieren.
2. Home Assistant neu starten.
3. Läuft das Add-on, meldet Home Assistant „Neues Gerät gefunden: KNX Monitor“. Bestätigen, fertig.

Ohne laufendes Add-on lässt sich die Integration nicht einrichten: Das Add-on übergibt Adresse und Zugang selbst.

## Was sie bringt

- **Sensoren:** Bus verbunden, Telegramme pro Minute und heute, Wiederholungen, Buslast, offene Alarme, letzter Alarm, Verfügbarkeit über 24 Stunden, Verlauf belegt, freier Speicher, Speicher knapp.
- **Schalter:** dauerhafte Aufzeichnung an und aus.
- **Geräte-Auslöser:** Wächter hat ausgelöst, Alarm oder Störung an und aus, Busverbindung verloren und wieder da.
- **Dienste:** `knx_monitor.create_report` erstellt den Anlagenbericht, `knx_monitor.export_history` speichert den Verlauf als Gruppenmonitor-Datei der ETS im Ordner `knx_monitor` der Konfiguration (ein Zeitraum bis 31 Tage oder alles als ZIP, höchstens 500 MB, ein Export zur Zeit). Beide nur für Administratoren.
- **Diagnose** zum Herunterladen auf der Geräteseite, ohne Namen, Adressen und Werte.
- **Reparaturhinweise**, wenn der Bus länger als 10 Minuten getrennt ist oder die Aufzeichnung wegen vollem Speicher pausiert.

Solange die Integration eingerichtet ist, kündigt das Add-on dieselben Entitäten nicht mehr über MQTT an. Entfernst du die Integration, kommt das MQTT-Gerät zurück.

## Rückmeldungen

Fehler und Wünsche bitte unter [regetskcob/KNX-Monitor/issues](https://github.com/regetskcob/KNX-Monitor/issues).

Dieses Repository wird aus dem Entwicklungsrepository erzeugt; Änderungen bitte als Issue statt als Pull Request.

Lizenz: GPLv3, wie KNX Monitor.

</details>
