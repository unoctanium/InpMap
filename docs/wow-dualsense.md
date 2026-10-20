# World of Warcraft with the emulated DualSense Edge

What you set up by hand so that World of Warcraft (Windows client under
Proton) uses InpMap's emulated DualSense Edge with all its buttons. The
emulation itself is described in
[configuration.md §3.5](configuration.md#35-emulating-a-dualsense-edge-emulate).

Checked with the WoW Classic beta client under Proton CachyOS on
2026-10-20. Other WoW versions read their gamepad files from their own
folder (`_retail_`, `_classic_`, `_classic_era_`, `_classic_beta_`, …);
the steps are the same.

## 1. InpMap and Steam

1. The profile has a gamepad output with `emulate = "dualsense-edge"`, and
   the udev rules of that profile are installed
   ([installation.md §3](installation.md#3-device-permissions)).
2. In Steam, WoW's properties → Controller → **"Disable Steam Input"**.
   Otherwise Steam hides the controller from WoW. Do not use Proton's
   `sdlinput` compatibility option.
3. Start InpMap before WoW. WoW looks for controllers when it starts; one
   that appears later may need a WoW restart.

## 2. In the game: use the controller

1. Turn the controller support on: Options → Controls → Controller, or
   `/console GamePadEnable 1`.
2. Let WoW use all controllers: `/console GamePadSingleActiveID 0`.

   WoW saves this setting. A value other than 0 selects one controller by
   its number, and the numbers change when controllers come and go (for
   example when InpMap is stopped). If WoW reacts to no controller at all,
   log in with the mouse and set it back to 0.

## 3. The View button: `PADBACK` instead of `PADSOCIAL`

For controllers with Sony's IDs, WoW's built-in configuration calls the
Create button `PADSOCIAL`. On the emulated DualSense that is the button
InpMap sends as `BTN_SELECT`: View on an Xbox-style pad. WoW does not let
you bind `PADSOCIAL` like the other buttons.

WoW reads its own controller configurations from extra files. A
configuration for exactly the emulated controller (vendor 1356 = 0x054C,
product 3570 = 0x0DF2) fixes the View button:

1. **Close WoW.** It rewrites its configuration files while it runs.
2. In WoW's folder, open `_classic_beta_/WTF/` (or your version's folder)
   and create the file **`GamePadConfig_InpMap.json`** with this content:

```json
{
    "configVersion": 4,
    "configs": [
        {
            "comment": "InpMap's emulated DualSense Edge: View/Create as PADBACK, Xbox button labels",
            "labelStyle": "Letters",
            "vendorID": 1356,
            "productID": 3570,
            "rawButtonMappings": [
                {"rawIndex": 0, "button": "PAD1"},
                {"rawIndex": 1, "button": "PAD2"},
                {"rawIndex": 2, "button": "PAD3"},
                {"rawIndex": 3, "button": "PAD4"},
                {"rawIndex": 4, "button": "PADBACK"},
                {"rawIndex": 5, "button": "PADSYSTEM"},
                {"rawIndex": 6, "button": "PADFORWARD"},
                {"rawIndex": 7, "button": "PADLSTICK"},
                {"rawIndex": 8, "button": "PADRSTICK"},
                {"rawIndex": 9, "button": "PADLSHOULDER"},
                {"rawIndex": 10, "button": "PADRSHOULDER"},
                {"rawIndex": 11, "button": "PADDUP"},
                {"rawIndex": 12, "button": "PADDDOWN"},
                {"rawIndex": 13, "button": "PADDLEFT"},
                {"rawIndex": 14, "button": "PADDRIGHT"},
                {"rawIndex": 15, "button": "PAD5"},
                {"rawIndex": 16, "button": "PADPADDLE1"},
                {"rawIndex": 17, "button": "PADPADDLE2"},
                {"rawIndex": 18, "button": "PADPADDLE3"},
                {"rawIndex": 19, "button": "PADPADDLE4"},
                {"rawIndex": 20, "button": "None"}
            ],
            "rawAxisMappings": [
                {"rawIndex": 0, "axis": "LStickX"},
                {"rawIndex": 1, "axis": "LStickY"},
                {"rawIndex": 2, "axis": "RStickX"},
                {"rawIndex": 3, "axis": "RStickY"},
                {"rawIndex": 4, "axis": "LTrigger"},
                {"rawIndex": 5, "axis": "RTrigger"}
            ],
            "axisConfigs": [
                {"axis": "LStickX", "shift": 0.0, "scale": 1.0},
                {"axis": "LStickY", "shift": 0.0, "scale": -1.0},
                {"axis": "RStickX", "shift": 0.0, "scale": 1.0},
                {"axis": "RStickY", "shift": 0.0, "scale": -1.0},
                {"axis": "GStickX", "shift": 0.0, "scale": 1.0},
                {"axis": "GStickY", "shift": 0.0, "scale": 1.0},
                {"axis": "PStickX", "shift": -0.5, "scale": 2.0},
                {"axis": "PStickY", "shift": -0.5, "scale": -2.0},
                {"axis": "LTrigger", "shift": 0.0, "scale": 1.0},
                {"axis": "RTrigger", "shift": 0.0, "scale": 1.0}
            ]
        }
    ]
}
```

3. Start WoW and bind the View button; it now shows as `PADBACK`.

What the file is: WoW's own entry for this controller, as WoW writes it
into `GamePadConfig_Default.json` ("Default Configuration for a 1356:3570
'DualSense Edge Wireless Controller'"), with two changes:

- `rawIndex` 4 (SDL's Back button, the DualSense's Create) is `PADBACK`
  instead of `PADSOCIAL`; everything else is unchanged.
- `labelStyle` is `"Letters"` (A, B, X, Y as on an Xbox controller)
  instead of `"Shapes"` (Cross, Circle, Square, Triangle). Keep `"Shapes"`
  if you prefer the PlayStation symbols.

Do not change `GamePadConfig_Default.json` itself: WoW overwrites it. WoW
loads your own `GamePadConfig_*.json` files after it and the AddOns file
last (see the comments at the top of `GamePadConfig_Default.json`).

To undo: close WoW and delete `GamePadConfig_InpMap.json`.

## 4. What WoW calls the buttons

| InpMap code | DualSense Edge | WoW |
|---|---|---|
| `BTN_SOUTH`, `BTN_EAST`, `BTN_X`, `BTN_Y` | Cross, Circle, Square, Triangle | `PAD1`, `PAD2`, `PAD3`, `PAD4` |
| `BTN_SELECT` | Create | `PADBACK` with the file of section 3, otherwise `PADSOCIAL` |
| `BTN_START` | Options | `PADFORWARD` |
| `BTN_MODE` | PS button | `PADSYSTEM` |
| `BTN_TL`, `BTN_TR` | L1, R1 | `PADLSHOULDER`, `PADRSHOULDER` |
| `BTN_THUMBL`, `BTN_THUMBR` | L3, R3 | `PADLSTICK`, `PADRSTICK` |
| `BTN_GRIPR2` | right back paddle | `PADPADDLE1` |
| `BTN_GRIPL2` | left back paddle | `PADPADDLE2` |
| `BTN_GRIPR` | right Fn button | `PADPADDLE3` |
| `BTN_GRIPL` | left Fn button | `PADPADDLE4` |

The triggers arrive as axes, which WoW turns into `PADLTRIGGER` and
`PADRTRIGGER`.
