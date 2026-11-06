# Validation

The repair was developed against Serpantinum 2.3.0 (a62f825), Quickshell and Qt 6 on an Arch Linux / Hyprland desktop.

- The original fault was reproduced: the system hicolor `index.theme` was missing while application image files still existed.
- Restoring a user-local index and selecting the installed Papirus theme allowed Qt to render all 93 visible installed application's icons in the local inventory check, including extensionless fallback.
- The live launcher was checked after restarting Serpantinum: Firefox, Files, Blender and the other visible entries displayed actual icons instead of checkerboards.
- The utility's dry run recognizes that installation as already fixed and proposes zero changes.
- Automated fixtures exercise missing/invalid indexes, XDG paths, theme preservation, unknown QML, symlinks, repeated application, backup restore, concurrent edits and injected write failure.

This is not a claim that every distribution, theme, Serpantinum version or tray icon has been tested. CI tests the repair engine on Python 3.10–3.13. Live restart testing covers the standard `serpantinumd` launcher.
