# Chuango Alarm

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration) [![GitHub Release](https://img.shields.io/github/v/release/NemoN/ha-chuango-ov300)](https://github.com/NemoN/ha-chuango-ov300/releases) [![GitHub License](https://img.shields.io/github/license/NemoN/ha-chuango-ov300)](LICENSE)

**[English](#features)** | **[Deutsch](#chuango-alarm-deutsch)**

Home Assistant integration for **Chuango OV-300** WiFi alarm systems via the DreamCatcher Live cloud service.

## Features

- Arm, disarm, and home-arm your alarm system
- Real-time status updates via MQTT
- Shows who changed the alarm state (user attribution)
- Diagnostic sensors (token expiration, device info)
- Multi-region support (EU, US, Asia, etc.)

## Supported Models

| Model | Status |
|-------|--------|
| [OV-300](https://chuango.de/en/products/smart-wifi-alarm-system-ov-300) | Tested |

## Testers Wanted

Testers for other Chuango WiFi alarm systems are wanted.  
If you use a different Chuango model, please open an issue and share your model name plus test results.

## Requirements

- A Chuango OV-300 alarm system
- An account in the **DreamCatcher Live** app ([Android](https://play.google.com/store/apps/details?id=com.dc.dreamcatcherlife) / [iOS](https://apps.apple.com/de/app/dreamcatcher-life/id1507718806))
- Home Assistant 2024.1 or newer

## Installation

### HACS (Recommended)

1. Open **HACS** in Home Assistant
2. Go to **Integrations** → **⋮** (three dots) → **Custom repositories**
3. Add `https://github.com/NemoN/ha-chuango-ov300` with category **Integration**
4. Search for **"Chuango Alarm"** and install it
5. Restart Home Assistant

**Or use this button:**

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=NemoN&repository=ha-chuango-ov300)

### Manual Installation

1. Download the latest release from [GitHub](https://github.com/NemoN/ha-chuango-ov300/releases)
2. Extract and copy `custom_components/chuango_alarm` to your `config/custom_components/` directory
3. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services**
2. Click **+ Add Integration**
3. Search for **"Chuango Alarm"**
4. In the DreamCatcher app, create a dedicated user for Home Assistant (separate email address).
5. Share your alarm system with that dedicated user in the DreamCatcher app.
6. Enter that dedicated user's credentials in the integration:

| Field | Description | Example |
|-------|-------------|---------|
| Country | Your country/region | Germany |
| E-Mail | DreamCatcher Live email | user@example.com |
| Password | DreamCatcher Live password | ••••••••• |

[![Add Integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=chuango_alarm)

## Entities

### Alarm Control Panel

| Entity | Description |
|--------|-------------|
| `alarm_control_panel.<device_name>_alarm` | Main alarm control |

**Supported States:**
- `disarmed` - System is disarmed
- `armed_away` - System is armed (away mode)
- `armed_home` - System is armed (home mode)
- `triggered` - Alarm is triggered

**Supported Actions:**
- Arm Away
- Arm Home
- Disarm
- Trigger

### Sensors

| Entity | Description |
|--------|-------------|
| `sensor.chuango_user` | Logged-in user info |
| `sensor.chuango_token_expiration` | Token validity timestamp |
| `sensor.<device>_device_type` | Device type identifier |
| `sensor.<device>_product_id` | Product ID |
| `sensor.<device>_device_id` | Device ID |

## Example Automations

### Notify on Alarm Trigger

```yaml
automation:
  - alias: "Alarm Triggered Notification"
    trigger:
      - platform: state
        entity_id: alarm_control_panel.ov300_alarm
        to: "triggered"
    action:
      - service: notify.mobile_app_phone
        data:
          title: "Alarm!"
          message: "The alarm has been triggered!"
          data:
            priority: high
```

### Arm Alarm When Leaving Home

```yaml
automation:
  - alias: "Arm Alarm on Leave"
    trigger:
      - platform: state
        entity_id: person.your_name
        from: "home"
    action:
      - service: alarm_control_panel.alarm_arm_away
        target:
          entity_id: alarm_control_panel.ov300_alarm
```

### Disarm Alarm When Arriving Home

```yaml
automation:
  - alias: "Disarm Alarm on Arrival"
    trigger:
      - platform: state
        entity_id: person.your_name
        to: "home"
    action:
      - service: alarm_control_panel.alarm_disarm
        target:
          entity_id: alarm_control_panel.ov300_alarm
```

## Troubleshooting

| Error | Cause | Solution |
|-------|-------|----------|
| `Invalid login` | Wrong credentials | Check email and password in DreamCatcher Live app |
| `Connection failed` | Network issue | Check internet connection, try again later |
| `Invalid country selection` | Unknown region | Select a valid country from the list |
| `No shared devices found` | No alarm system shared with this account | Create a dedicated HA user in DreamCatcher app, share the alarm system with that user, then log in with this user in HA |
| `Already configured` | Duplicate setup | Remove existing integration first |

### Debug Logging

Add this to your `configuration.yaml` to enable debug logging:

```yaml
logger:
  default: info
  logs:
    custom_components.chuango_alarm: debug
```

## Known Limitations

- **Cloud-dependent**: Requires internet connection (no local control)
- **API rate limits**: Excessive requests may be throttled
- **Token refresh**: Token expires after ~30 days, auto-refreshed when < 12h remaining

## Hardware Info

### OV-300

- **SoC**: WinnerMicro W800
- **Documentation**: [W800 Developer Guide](https://doc.winnermicro.net/w800/en/latest/soc_guides/index.html)
- **Specification**: [W800 Spec V2.0](http://ask.winnermicro.com/uploads/20241203/62e2b1e36dd2355a064bd60636ff66ab.pdf)

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Submit a pull request

For bugs and feature requests, please [open an issue](https://github.com/NemoN/ha-chuango-ov300/issues).

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Credits

- **Author**: [@NemoN](https://github.com/NemoN)

---

# Chuango Alarm (Deutsch)

Home Assistant Integration für **Chuango OV-300** WLAN-Alarmanlagen über den DreamCatcher Live Cloud-Dienst.

## Funktionen

- Scharf-, Unscharf- und Zuhause-Schaltung der Alarmanlage
- Echtzeit-Statusaktualisierung via MQTT
- Zeigt an, wer den Alarmzustand geändert hat
- Diagnosesensoren (Token-Ablauf, Geräteinformationen)
- Multi-Region-Unterstützung (EU, US, Asien, etc.)

## Unterstützte Modelle

| Modell | Status |
|--------|--------|
| [OV-300](https://chuango.de/products/smart-wifi-alarm-system-ov-300) | Getestet |

## Tester Gesucht

Es werden Tester für weitere Chuango WLAN-Alarmanlagen gesucht.  
Wenn du ein anderes Chuango-Modell nutzt, erstelle bitte ein Issue mit Modellname und Testergebnissen.

## Voraussetzungen

- Eine Chuango OV-300 Alarmanlage
- Ein Konto in der **DreamCatcher Live** App ([Android](https://play.google.com/store/apps/details?id=com.dc.dreamcatcherlife) / [iOS](https://apps.apple.com/de/app/dreamcatcher-life/id1507718806))
- Home Assistant 2024.1 oder neuer

## Installation

### HACS (Empfohlen)

1. **HACS** in Home Assistant öffnen
2. Gehe zu **Integrationen** → **⋮** (drei Punkte) → **Benutzerdefinierte Repositories**
3. Füge `https://github.com/NemoN/ha-chuango-ov300` mit Kategorie **Integration** hinzu
4. Suche nach **"Chuango Alarm"** und installiere es
5. Home Assistant neu starten

**Oder nutze diesen Button:**

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=NemoN&repository=ha-chuango-ov300)

### Manuelle Installation

1. Lade das neueste Release von [GitHub](https://github.com/NemoN/ha-chuango-ov300/releases) herunter
2. Entpacke und kopiere `custom_components/chuango_alarm` in dein `config/custom_components/` Verzeichnis
3. Home Assistant neu starten

## Konfiguration

1. Gehe zu **Einstellungen** → **Geräte & Dienste**
2. Klicke auf **+ Integration hinzufügen**
3. Suche nach **"Chuango Alarm"**
4. Lege in der DreamCatcher-App einen eigenen Benutzer für Home Assistant an (separate E-Mail-Adresse).
5. Gib diesem Benutzer in der DreamCatcher-App die Alarmanlage frei.
6. Melde die Integration in Home Assistant mit diesem extra Benutzer an:

| Feld | Beschreibung | Beispiel |
|------|--------------|----------|
| Land | Dein Land/Region | Germany |
| E-Mail | DreamCatcher Live E-Mail | benutzer@beispiel.de |
| Passwort | DreamCatcher Live Passwort | ••••••••• |

[![Integration hinzufügen](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=chuango_alarm)

## Entitäten

### Alarm-Zentrale

| Entität | Beschreibung |
|---------|--------------|
| `alarm_control_panel.<gerätename>_alarm` | Haupt-Alarmsteuerung |

**Unterstützte Zustände:**
- `disarmed` - System ist unscharf
- `armed_away` - System ist scharf (Abwesend-Modus)
- `armed_home` - System ist scharf (Zuhause-Modus)
- `triggered` - Alarm wurde ausgelöst

**Unterstützte Aktionen:**
- Scharf schalten (Abwesend)
- Scharf schalten (Zuhause)
- Unscharf schalten
- Alarm auslösen

### Sensoren

| Entität | Beschreibung |
|---------|--------------|
| `sensor.chuango_user` | Angemeldeter Benutzer |
| `sensor.chuango_token_expiration` | Token-Gültigkeitszeitstempel |
| `sensor.<gerät>_device_type` | Gerätetyp |
| `sensor.<gerät>_product_id` | Produkt-ID |
| `sensor.<gerät>_device_id` | Geräte-ID |

## Beispiel-Automatisierungen

### Benachrichtigung bei Alarm

```yaml
automation:
  - alias: "Alarm ausgelöst Benachrichtigung"
    trigger:
      - platform: state
        entity_id: alarm_control_panel.ov300_alarm
        to: "triggered"
    action:
      - service: notify.mobile_app_handy
        data:
          title: "Alarm!"
          message: "Der Alarm wurde ausgelöst!"
          data:
            priority: high
```

### Alarm scharf schalten beim Verlassen

```yaml
automation:
  - alias: "Alarm scharf beim Verlassen"
    trigger:
      - platform: state
        entity_id: person.dein_name
        from: "home"
    action:
      - service: alarm_control_panel.alarm_arm_away
        target:
          entity_id: alarm_control_panel.ov300_alarm
```

### Alarm unscharf schalten bei Ankunft

```yaml
automation:
  - alias: "Alarm unscharf bei Ankunft"
    trigger:
      - platform: state
        entity_id: person.dein_name
        to: "home"
    action:
      - service: alarm_control_panel.alarm_disarm
        target:
          entity_id: alarm_control_panel.ov300_alarm
```

## Fehlerbehebung

| Fehler | Ursache | Lösung |
|--------|---------|--------|
| `Invalid login` | Falsche Anmeldedaten | E-Mail und Passwort in der DreamCatcher Live App prüfen |
| `Connection failed` | Netzwerkproblem | Internetverbindung prüfen, später erneut versuchen |
| `Invalid country selection` | Unbekannte Region | Ein gültiges Land aus der Liste wählen |
| `No shared devices found` | Für diesen Account wurde keine Alarmanlage freigegeben | In der DreamCatcher-App einen separaten HA-Benutzer anlegen, Anlage für diesen Benutzer freigeben und mit diesem Benutzer in HA anmelden |
| `Already configured` | Doppelte Einrichtung | Bestehende Integration zuerst entfernen |

### Debug-Logging

Füge dies zu deiner `configuration.yaml` hinzu, um Debug-Logging zu aktivieren:

```yaml
logger:
  default: info
  logs:
    custom_components.chuango_alarm: debug
```

## Bekannte Einschränkungen

- **Cloud-abhängig**: Erfordert Internetverbindung (keine lokale Steuerung)
- **API-Ratenlimits**: Übermäßige Anfragen können gedrosselt werden
- **Token-Aktualisierung**: Token läuft nach ~30 Tagen ab, wird automatisch erneuert wenn < 12h verbleibend

## Hardware-Info

### OV-300

- **SoC**: WinnerMicro W800
- **Dokumentation**: [W800 Developer Guide](https://doc.winnermicro.net/w800/en/latest/soc_guides/index.html)
- **Spezifikation**: [W800 Spec V2.0](http://ask.winnermicro.com/uploads/20241203/62e2b1e36dd2355a064bd60636ff66ab.pdf)

## Mitwirken

Beiträge sind willkommen! Bitte:

1. Forke das Repository
2. Erstelle einen Feature-Branch
3. Reiche einen Pull Request ein

Für Fehler und Feature-Anfragen bitte ein [Issue erstellen](https://github.com/NemoN/ha-chuango-ov300/issues).
