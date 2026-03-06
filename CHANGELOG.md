# Changelog

## 0.5.3

- Fixed part renames from the app so updated sensor/keyfob names propagate correctly in Home Assistant
- Improved SOS button naming and Lovelace example configuration
- Refined performance for event history state handling

## 0.5.2

- Added SOS trigger support via the alarm control panel and dedicated SOS button
- Improved alarm origin/source labeling for SOS, keyfob, and app-triggered events
- Improved entity icons and update advisory localization

## 0.5.1

- Added Chinese translations (`zh-Hans`, `zh-Hant`) for the integration
- Synced base English localization keys with the current feature set
- Moved release notes to dedicated `CHANGELOG.md`

## 0.5.0

- Added firmware version sensor and firmware update entity
- Added entry/exit delay controls and delay tone switches
- Added RF test mode switch
- Added per-part zone select, per-part enabled switch, and per-keyfob SOS switch
- Improved command/state sync stability and reduced part-state flicker

## 0.4.2

- Added extended alarm event type mapping
- Added translations for new event types
- Updated dashboard card examples

## 0.4.1

- Improved translation support for entity names
- Improved live event delivery and history updates
- Added updated device page screenshots

## 0.4.0

- Added live event log entity with cloud history
- Added AC power status binary sensor
- Added dashboard card example for alarm history

## 0.3.0

- Added alarm settings (volume, duration, arm/disarm beep)
- Added accessories as sub-devices
- Added accessory refresh controls
- Added triggered-by tracking
- Improved integration shutdown behavior

## 0.2.3

- Initial public release
- Added alarm control panel support
- Added real-time status updates
- Added user attribution and diagnostic sensors
- Added multi-region support
