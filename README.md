# Busclear for Home Assistant

Integration for the [Busclear add-on](https://github.com/regetskcob/KNX-Monitor): the add-on becomes the device "Busclear" with sensors, a switch, event entities, device triggers and conditions, services, diagnostics and repairs, no MQTT broker needed. It also works with a Busclear Box or the Docker container, without Supervisor.

## Requirements

- Home Assistant 2025.1 or newer
- With Supervisor (Home Assistant OS or Supervised): Busclear add-on 1.9.7 or newer; per-watcher triggers and the "stopped sending" repair need 1.9.10 or newer
- Without Supervisor (Home Assistant Container): a Busclear Box or the Docker container with Busclear 1.9.10 or newer; event entities and device triggers need 1.12.0 or newer

## Installation

1. In HACS, add `https://github.com/regetskcob/KNX-Monitor-HA` as a *custom repository* of type *Integration* and install **Busclear**.
2. Restart Home Assistant.
3. With the add-on running, Home Assistant shows "New device found: Busclear". Confirm, done.

### Busclear Box or Docker container

1. On the box (or container) open `/pair` in the browser, log in with the box password, tick **Verwalten** (the integration needs a device with admin rights) and **Schlüssel direkt anzeigen** (from Busclear 1.12 on the page otherwise shows a one-time code for the app, which the integration cannot use) and create the link. Docker: set `LAN_ACCESS=yes` unless Home Assistant runs on the same host.
2. *Settings → Devices & services → Add integration → Busclear*. Without the add-on, Home Assistant asks for the address of the box or container (e.g. `knx-box.local` or `192.168.1.20:8765`; empty takes the one from the link) and the pairing link (`knxmonitor://box?url=…&key=…`).

The access key goes only to that address, redirects are not followed. If the box has its own certificate, the link carries its fingerprint: the integration then speaks HTTPS and accepts only that certificate ("Certificate does not match the link" otherwise). Without one the connection is not encrypted. Revoke the device on `/pair` to take the access away. If the box no longer accepts the key (device revoked or without admin rights), Home Assistant asks to pair again: create a new link on `/pair` and paste it; the address stays.

Event entities and device triggers work as with the add-on from Busclear 1.12.0 on: the integration then listens to the event channel of the box or container (`/ws/events`) and fires the same events in Home Assistant (`knx_monitor_watcher`, `knx_monitor_alarm`, `knx_monitor_bus`, with `config_entry_id` added). If the connection drops, it reconnects by itself and gets the events it missed, as far as the box still has them (the last 64). With an older box there are no event entities and no device triggers; sensors, switch, conditions, services, diagnostics and repairs work the same. After updating the box the integration notices the channel within a minute and reloads.

## What it adds

- **Sensors:** bus connected, telegrams per minute and today, repeats, bus load, open alarms, last alarm, availability over 24 hours, history size, free space, low space.
- **Switch:** continuous recording on and off.
- **Event entities:** watcher and alarm, with the same IDs as on the MQTT device; the logbook shows every firing with its type.
- **Device triggers:** a watcher fired, one trigger per watcher with its name, alarm or fault on and off, bus connection lost and back.
- **Device conditions:** bus connected, bus disconnected, recording on, alarm open, low space. They read the integration's own entities and are not met while the add-on is unreachable.
- **Services:** `knx_monitor.create_report` creates the installation report, `knx_monitor.export_history` saves the history as an ETS group monitor file in the `knx_monitor` folder of the configuration (up to 31 days, or everything as a zip, at most 500 MB, one export at a time). Both are for administrators only.
- **Health check:** if the server's health check is switched on (add-on option "Health check for Home Assistant", `HEALTH_CHECK=true` for Docker and the Busclear Box), the sensor "Health" shows `ok`, `hints` or `faults` with the counts and the time of the last run, and the diagnostic sensor "Health findings" the number of findings. The server checks its recorded history once a day; `knx_monitor.run_health_check` (administrators only) runs it now and returns the findings as response data. Nothing is sent on the bus.
- **Diagnostics** download on the device page, without names, addresses or values.
- **Repairs** when the bus has been disconnected for more than 10 minutes, recording paused because the disk is full, or a group address that usually sends regularly stopped ("1/2/3 Temperature bathroom stopped sending", from 5 addresses on one summary). "Ignore" tells the add-on to stop reporting it; once the address sends again, the repair goes away and the address is watched again. Nothing is reported while recording is off or the bus is disconnected.

While the integration is set up, the add-on stops announcing the same entities over MQTT. Remove the integration and the MQTT device comes back.

## Removing

Settings → Devices & services → Busclear → three dots → Delete. Entities, device triggers and repairs of the integration go away; automations that use them stop working and are marked by Home Assistant. The add-on, the box and their recordings are not touched, and the add-on announces its MQTT device again. On a Busclear Box or Docker container the paired access "Home Assistant" stays until you revoke it on its `/pair` page. To remove the code as well, remove the repository in HACS and restart Home Assistant.

## Feedback

Bugs and wishes at [regetskcob/KNX-Monitor/issues](https://github.com/regetskcob/KNX-Monitor/issues).

This repository is generated from the development repository; please open an issue instead of a pull request.

License: GPLv3, like Busclear.

---

<details>
<summary>🇩🇪 Deutsch</summary>

# Busclear für Home Assistant

Integration für das [Busclear-Add-on](https://github.com/regetskcob/KNX-Monitor): Das Add-on wird zum Gerät „Busclear“ mit Sensoren, Schalter, Ereignis-Entitäten, Geräte-Auslösern und -Bedingungen, Diensten, Diagnose und Reparaturhinweisen, ganz ohne MQTT-Broker. Sie geht auch mit einer Busclear Box oder dem Docker-Container, ohne Supervisor.

## Voraussetzungen

- Home Assistant ab 2025.1
- Mit Supervisor (Home Assistant OS oder Supervised): Busclear-Add-on ab 1.9.7; Auslöser je Wächter und der Hinweis „sendet nicht mehr“ ab 1.9.10
- Ohne Supervisor (Home Assistant Container): Busclear Box oder Docker-Container mit Busclear ab 1.9.10; Ereignis-Entitäten und Geräte-Auslöser ab 1.12.0

## Installation

1. In HACS unter *Benutzerdefinierte Repositories* `https://github.com/regetskcob/KNX-Monitor-HA` als *Integration* hinzufügen und **Busclear** installieren.
2. Home Assistant neu starten.
3. Läuft das Add-on, meldet Home Assistant „Neues Gerät gefunden: Busclear“. Bestätigen, fertig.

### Busclear Box oder Docker-Container

1. Auf der Box (oder im Container) `/pair` im Browser öffnen, mit dem Box-Passwort anmelden, **Verwalten** ankreuzen (die Integration braucht ein Gerät mit Admin-Recht), dazu **Schlüssel direkt anzeigen** (ab Busclear 1.12 zeigt die Seite sonst einen Einmal-Code für die App, mit dem die Integration nichts anfangen kann), und den Link erzeugen. Docker: `LAN_ACCESS=yes` setzen, außer Home Assistant läuft auf demselben Rechner.
2. *Einstellungen → Geräte & Dienste → Integration hinzufügen → Busclear*. Ohne Add-on fragt Home Assistant nach der Adresse der Box oder des Containers (z. B. `knx-box.local` oder `192.168.1.20:8765`; leer nimmt die aus dem Link) und nach dem Kopplungslink (`knxmonitor://box?url=…&key=…`).

Der Zugangsschlüssel geht nur an diese Adresse, Weiterleitungen werden nicht befolgt. Hat die Box ein eigenes Zertifikat, steht sein Fingerabdruck im Link: Die Integration spricht dann HTTPS und nimmt nur dieses Zertifikat an (sonst „Zertifikat passt nicht zum Link“). Ohne Zertifikat ist die Verbindung unverschlüsselt. Wer das Gerät auf `/pair` sperrt, nimmt den Zugang weg. Nimmt die Box den Schlüssel nicht mehr an (Gerät gesperrt oder ohne Admin-Recht), fragt Home Assistant nach einer neuen Kopplung: auf `/pair` einen neuen Link erzeugen und einfügen, die Adresse bleibt.

Ereignis-Entitäten und Geräte-Auslöser gehen ab Busclear 1.12.0 wie mit dem Add-on: Die Integration hört dann auf den Ereigniskanal der Box oder des Containers (`/ws/events`) und löst dieselben Ereignisse in Home Assistant aus (`knx_monitor_watcher`, `knx_monitor_alarm`, `knx_monitor_bus`, dazu `config_entry_id`). Reißt die Verbindung ab, verbindet sie sich selbst neu und holt die verpassten Ereignisse nach, soweit die Box sie noch hat (die letzten 64). Mit einer älteren Box gibt es keine Ereignis-Entitäten und keine Geräte-Auslöser; Sensoren, Schalter, Bedingungen, Dienste, Diagnose und Reparaturhinweise gehen genauso. Nach dem Update der Box merkt die Integration den Kanal innerhalb einer Minute und lädt sich neu.

## Was sie bringt

- **Sensoren:** Bus verbunden, Telegramme pro Minute und heute, Wiederholungen, Buslast, offene Alarme, letzter Alarm, Verfügbarkeit über 24 Stunden, Verlauf belegt, freier Speicher, Speicher knapp.
- **Schalter:** dauerhafte Aufzeichnung an und aus.
- **Ereignis-Entitäten:** Wächter und Alarm, mit denselben IDs wie beim MQTT-Gerät; das Logbuch zeigt jede Auslösung mit ihrem Typ.
- **Geräte-Auslöser:** ein Wächter hat ausgelöst, ein Auslöser je Wächter mit seinem Namen, Alarm oder Störung an und aus, Busverbindung verloren und wieder da.
- **Geräte-Bedingungen:** Bus ist verbunden, Bus ist getrennt, Aufzeichnung läuft, Alarm offen, Speicher knapp. Sie lesen die eigenen Entitäten und sind nicht erfüllt, solange das Add-on nicht erreichbar ist.
- **Dienste:** `knx_monitor.create_report` erstellt den Anlagenbericht, `knx_monitor.export_history` speichert den Verlauf als Gruppenmonitor-Datei der ETS im Ordner `knx_monitor` der Konfiguration (ein Zeitraum bis 31 Tage oder alles als ZIP, höchstens 500 MB, ein Export zur Zeit). Beide nur für Administratoren.
- **Gesundheitsprüfung:** Ist die Gesundheitsprüfung des Servers eingeschaltet (Add-on-Option „Gesundheitsprüfung für Home Assistant“, bei Docker und der Busclear Box `HEALTH_CHECK=true`), zeigt der Sensor „Gesundheit“ `ok`, `hints` oder `faults` mit den Anzahlen und der Zeit des letzten Laufs, der Diagnosesensor „Befunde der Gesundheitsprüfung“ die Zahl der Befunde. Der Server prüft seinen aufgezeichneten Verlauf einmal täglich; `knx_monitor.run_health_check` (nur für Administratoren) startet die Prüfung sofort und liefert die Befunde als Antwortdaten. Dabei geht nichts auf den Bus.
- **Diagnose** zum Herunterladen auf der Geräteseite, ohne Namen, Adressen und Werte.
- **Reparaturhinweise**, wenn der Bus länger als 10 Minuten getrennt ist, die Aufzeichnung wegen vollem Speicher pausiert oder eine Gruppenadresse, die sonst regelmäßig sendet, verstummt ist („1/2/3 Temperatur Bad sendet nicht mehr“, ab 5 Adressen ein Sammelhinweis). „Ignorieren“ sagt dem Add-on, sie nicht mehr zu melden; sendet die Adresse wieder, verschwindet der Hinweis und sie wird wieder beobachtet. Solange die Aufzeichnung aus oder der Bus getrennt ist, kommt kein solcher Hinweis.

Solange die Integration eingerichtet ist, kündigt das Add-on dieselben Entitäten nicht mehr über MQTT an. Entfernst du die Integration, kommt das MQTT-Gerät zurück.

## Entfernen

Einstellungen → Geräte & Dienste → Busclear → drei Punkte → Löschen. Entitäten, Geräte-Auslöser und Reparaturhinweise der Integration verschwinden; Automationen, die sie nutzen, laufen nicht mehr und werden von Home Assistant markiert. Add-on, Box und ihre Aufzeichnungen bleiben unberührt, und das Add-on kündigt sein MQTT-Gerät wieder an. Auf einer Busclear Box oder im Docker-Container bleibt der gekoppelte Zugang „Home Assistant“ bestehen, bis du ihn dort auf der Seite `/pair` sperrst. Um auch den Code zu entfernen, das Repository in HACS entfernen und Home Assistant neu starten.

## Rückmeldungen

Fehler und Wünsche bitte unter [regetskcob/KNX-Monitor/issues](https://github.com/regetskcob/KNX-Monitor/issues).

Dieses Repository wird aus dem Entwicklungsrepository erzeugt; Änderungen bitte als Issue statt als Pull Request.

Lizenz: GPLv3, wie Busclear.

</details>
