# Earthsplorer1792

Explore Google Street View from a desktop window using a PS5 DualSense over USB or Bluetooth. The running app is named **Earthsplorer** followed by the combined physical line count of its Python, HTML, CSS, and JavaScript application source. The count includes blank and comment lines and excludes tests, documentation, dependencies, and downloaded assets.

## Install and run

Use Python 3.11–3.13. Pygame 2.6.1 provides desktop wheels through Python 3.13. Use a Python installation that matches your operating system and CPU.

**macOS or Linux**

```sh
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

**Windows PowerShell**

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

### Configure Google Maps

1. Create or select a Google Cloud project, enable billing, and enable **Maps JavaScript API**.
2. Create a dedicated API key. Under **Application restrictions**, select **Websites** and add `http://127.0.0.1:8765` as the allowed referrer. Enter the origin with the port and omit path-specific rules. Under **API restrictions**, restrict the key to **Maps JavaScript API**.
3. Set `GOOGLE_MAPS_API_KEY` in `.env`. Keep that file local. The embedded browser receives the key to load Google's JavaScript API, so the Cloud restrictions are important. For a classroom project, use a development key and configure usage quotas in the Cloud console.

Qt WebEngine loads the viewer over HTTP from a static server bound to `127.0.0.1` on your own computer. This gives Google an HTTP origin for the website restriction. Qt's WebChannel uses Chromium's built-in transport. There is no deployed backend. If you change the port, add the matching origin to the key restriction.

[Google API setup](https://developers.google.com/maps/documentation/javascript/get-api-key) · [Google key security guidance](https://developers.google.com/maps/api-security-best-practices)

### Connect a DualSense and launch

- For USB, use a USB-C cable that supports data and connect the controller directly to the computer.
- For Bluetooth, disconnect USB, turn the controller off, then hold **Create** and **PS** until the light bar flashes. Select the controller in your operating system's Bluetooth settings. The product name can appear as **DualSense Wireless Controller** or **Wireless Controller**.
- Start the app. The connection name appears in the top bar. You can reconnect while the app is running.

```sh
python main.py
python main.py --mock-controller
python main.py --start=13.73830,100.52956 --port 8765
```

On Windows, replace `python` with `.venv\Scripts\python.exe` if you are using the environment without activating it. Street View starts facing north on Phaya Thai Road by Chulalongkorn University in Bangkok.

[PlayStation DualSense pairing instructions](https://www.playstation.com/en-us/support/hardware/pair-dualsense-controller-bluetooth/)

## Controls

| DualSense | Keyboard mock | Action |
| --- | --- | --- |
| Right stick | Arrow keys | Look horizontally or vertically |
| Left stick up or R2 | E | Move along the connected route closest to the camera heading |
| Left stick down or L2 | Q | Reverse through successfully visited panoramas |
| Left stick left/right | J / L | Highlight a connected route. Center the stick between flicks. |
| Cross | Enter | Follow the highlighted route |
| Touchpad click | World map button | Open the location selector |
| Options | P | Pause or resume controller input |
| D-pad up/down | ] / [ | Raise or lower camera sensitivity |

Street View moves between individual panoramas. Hold the left stick up or down to keep driving. Forward movement requires a route within 60° of the camera heading. Flick the left stick sideways and press Cross to take a turn while looking in another direction. The triggers still work for single steps.

Click the **touchpad** or select **World map**. Pan with the left stick, zoom with **L2/R2**, and press **Cross** to drive at the reticle. Click the touchpad again or press **Circle** to close the map. You can also click a road or choose a preset. The selector checks for a nearby outdoor panorama with connections before moving you there. A successful jump starts a new navigation history.

Search accepts preset names and latitude/longitude pairs with the existing Maps JavaScript API key. For general place names and addresses, enable **Geocoding API** in the same Google Cloud project and add it to the key's API restrictions. [Google Geocoding setup](https://developers.google.com/maps/documentation/javascript/geocoding)

**Music on** toggles the looping soundtrack. **Sound on** toggles navigation and selection cues separately.

## Team responsibilities

Start with `controller.py` and `navigation.py` to see how the game works. They use functions and dictionaries for input and navigation state. `main.py` connects those functions to the window. The two classes in `bridge.py` connect the viewer to Qt and serve its local web files.

| Member | Files | Responsibility |
| --- | --- | --- |
| 1 | `controller.py`, `tests/test_controller.py` | SDL controller mappings, analog normalization, dead zones, button edges, and reconnection |
| 2 | `navigation.py`, `tests/test_navigation.py` | Heading math, intersection selection, movement state, and history |
| 3 | `main.py`, `bridge.py`, `config.py`, `static/` | Qt window, settings, WebChannel, and panorama rendering |

```text
DualSense → Pygame/SDL → Python input and navigation → QWebChannel → Google Street View
                    ← current heading, location, route links, and movement result ←
```

The standard-library tests run without Qt, Google credentials, or controller hardware.

```sh
python -m unittest discover -s tests -v
```

## Limits and troubleshooting

- **Missing or rejected API key** · Check `.env`, billing, the enabled API, and the exact loopback origin. Restart the application after editing `.env`. A Google development watermark can indicate a billing or key configuration error.
- **No image at the start** · Try `--start=LAT,LNG` at coordinates with Street View coverage. Coverage and connected routes vary by panorama. A location without links can still be visible.
- **Controller disconnected** · Reconnect in the operating system or try a USB data cable. Check that Steam Input or a controller remapping utility has not captured the physical device. SDL uses separate mappings for device GUIDs and platforms. If SDL does not recognize your controller, set `SDL_GAMECONTROLLERCONFIG` in `.env` to an SDL mapping line for its GUID and restart. SDL maps the axes and buttons to standard controller names before Python reads them. [SDL mapping format](https://wiki.libsdl.org/SDL2/SDL_GameControllerAddMapping)
- **Local port in use** · Launch with a different `--port` and authorize its origin in Google Cloud.
- **Platform compatibility** · The app needs a desktop session and PySide6/Pygame wheels for your OS and CPU. The current PySide6 wheels require macOS 14 or later on macOS. Testing on Apple silicon confirmed browser startup, DualSense detection, and input from the left stick, R2, and L2. Live Maps loading, the remaining physical controls, and Windows/Linux desktop behavior still need verification.
- **Interrupted session** · Reload the viewer to retry a stalled or failed load. Panorama IDs and navigation history are kept for the current viewer session and reset on reload.
