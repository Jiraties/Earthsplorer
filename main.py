"""Run the desktop application, coordinating input, navigation, and Street View."""

import argparse
import sys
from math import isfinite
from time import monotonic

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineNavigationRequest
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from bridge import ViewerBridge, serve_viewer
from config import PORT, ROOT, START, application_name, load_settings
from controller import (
    close_controller, map_input, new_input_state, open_controller, poll_controller, raw_input,
)
from navigation import (
    can_update, finish_move, forward_route, make_route, new_navigation, route_label,
    select_direction, selected_route, start_move, update_navigation,
)

MOCK_BUTTONS = {
    "e": "forward", "q": "back", "enter": "confirm",
    "p": "pause", "]": "faster", "[": "slower",
}
MOCK_KEYS = set(MOCK_BUTTONS) | {"arrowup", "arrowdown", "arrowleft", "arrowright", "j", "l"}
CONTROLLER_HINTS = (
    ("L Stick ↑/↓", "Drive"), ("L Stick ←/→", "Select"), ("R Stick", "Look"),
    ("✕", "Confirm"), ("Options", "Pause"), ("D-pad ↑/↓", "Sensitivity"),
)
MOCK_HINTS = (
    ("E", "Forward"), ("Q", "Back"), ("J / L", "Select"), ("Arrows", "Look"),
    ("Enter", "Confirm"), ("P", "Pause"), ("[ / ]", "Sensitivity"),
)
COMPASS_DIRECTIONS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
DRIVE_REPEAT_INTERVAL = 0.55
MAP_ACTIONS = (
    ("cancel", "close"), ("map", "close"), ("pause", "close"),
    ("confirm", "drop"), ("forward", "in"), ("back", "out"),
)


def label(text: str, style: str = "") -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setObjectName(style)
    return widget


def open_new_window(request):
    url = request.requestedUrl()
    if request.isUserInitiated() and url.scheme() in {"http", "https"}:
        QDesktopServices.openUrl(url)


def allow_viewer_navigation(request, home_url):
    url = request.url()
    if not request.isMainFrame() or url == home_url:
        return

    # Keep external sites outside the viewer, where they cannot use its WebChannel.
    request.reject()
    link_clicked = QWebEngineNavigationRequest.NavigationType.LinkClickedNavigation
    if request.navigationType() == link_clicked and url.scheme() in {"http", "https"}:
        QDesktopServices.openUrl(url)


def create_game(name, key, start, port, mock):
    window = QMainWindow()
    window.setWindowTitle(name)
    window.resize(1100, 720)
    window.setMinimumSize(620, 420)

    view = QWebEngineView()
    game = {
        "window": window,
        "view": view,
        "url": QUrl(f"http://127.0.0.1:{port}/"),
        "nav": new_navigation(),
        "mock": mock,
        "reader": None,
        "mock_input_state": new_input_state(),
        "pressed": set(),
        "sensitivity": 1.0,
        "paused": False,
        "viewer_ready": False,
        "map_open": False,
        "wait_for_stick_center": False,
        "last_poll": monotonic(),
        "controller_error": "",
    }
    connect_viewer(game, key, start)
    load_sounds(game)
    connect_controls(game)
    build_ui(game, name)

    timer = QTimer(window, interval=16)
    timer.timeout.connect(lambda: poll(game))
    timer.start()
    game["timer"] = timer
    startup_timer = QTimer(window, interval=30000, singleShot=True)
    startup_timer.timeout.connect(
        lambda: on_viewer_failure(game, "Street View did not start. Reload the viewer to try again.")
    )
    game["startup_timer"] = startup_timer
    reload(game)
    return game


def connect_viewer(game, key, start):
    view = game["view"]
    page = view.page()
    page.newWindowRequested.connect(open_new_window)
    page.navigationRequested.connect(lambda request: allow_viewer_navigation(request, game["url"]))

    mock_keys = sorted(MOCK_KEYS) if game["mock"] else []
    bridge = ViewerBridge(key, start, mock_keys, game["window"])
    channel = QWebChannel(page)
    channel.registerObject("viewer", bridge)
    page.setWebChannel(channel)
    game["bridge"] = bridge
    game["channel"] = channel

    bridge.state_received.connect(lambda state: update_state(game, state))
    bridge.movement_finished.connect(lambda error, state: on_move(game, error, state))
    bridge.viewer_failed.connect(lambda message: on_viewer_failure(game, message))
    bridge.map_toggled.connect(lambda opened: on_map_toggled(game, opened))
    bridge.location_changed.connect(lambda state: on_location_changed(game, state))
    view.loadFinished.connect(lambda ok: on_page_loaded(game, ok))
    page.renderProcessTerminated.connect(
        lambda *_: on_viewer_failure(game, "The embedded browser stopped. Reload the viewer.")
    )


def connect_controls(game):
    if game["mock"]:
        game["bridge"].key_changed.connect(lambda key, pressed: on_key(game, key, pressed))
        QApplication.instance().applicationStateChanged.connect(lambda state: clear_keys(game, state))
    else:
        try:
            game["reader"] = open_controller()
        except (ImportError, RuntimeError) as error:
            game["controller_error"] = f"Controller unavailable: {error}"


def load_sounds(game):
    sounds_dir = ROOT / "static" / "sounds"
    game["sounds"] = {}
    for cue in ("move", "select", "blocked", "arrive"):
        sound = QSoundEffect(game["window"])
        sound.setSource(QUrl.fromLocalFile(str(sounds_dir / f"{cue}.wav")))
        sound.setVolume(0.35)
        game["sounds"][cue] = sound

    music = QSoundEffect(game["window"])
    music.setSource(QUrl.fromLocalFile(str(sounds_dir / "drive-loop.wav")))
    music.setLoopCount(QSoundEffect.Loop.Infinite.value)
    music.setVolume(0.23)
    game["music"] = music


def stop_game(game):
    game["timer"].stop()
    game["music"].stop()
    if game["reader"] is not None:
        close_controller(game["reader"])


def build_ui(game, name):
    root = QWidget()
    layout = QVBoxLayout(root)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    layout.addLayout(build_toolbar(game, name))
    layout.addWidget(game["view"], stretch=1)
    layout.addWidget(build_hud(game))
    root.setStyleSheet((ROOT / "static" / "hud.qss").read_text(encoding="utf-8"))
    game["window"].setCentralWidget(root)


def build_toolbar(game, name):
    top = QHBoxLayout()
    top.setContentsMargins(18, 8, 12, 8)
    top.setSpacing(14)
    top.addWidget(label(name, "title"))
    top.addStretch()
    game["connection"] = label("", "connection")
    top.addWidget(game["connection"])
    game["map_button"] = QPushButton("World map")
    game["map_button"].setObjectName("map")
    game["map_button"].clicked.connect(lambda: show_map(game))
    map_control = QVBoxLayout()
    map_control.setSpacing(3)
    map_control.addWidget(game["map_button"])
    if not game["mock"]:
        shortcut = label("Touchpad", "hint")
        shortcut.setAlignment(Qt.AlignmentFlag.AlignCenter)
        map_control.addWidget(shortcut)
    top.addLayout(map_control)
    game["sound_button"] = QPushButton("Sound on")
    game["sound_button"].setCheckable(True)
    game["sound_button"].setChecked(True)
    game["sound_button"].toggled.connect(
        lambda enabled: game["sound_button"].setText("Sound on" if enabled else "Sound off")
    )
    top.addWidget(game["sound_button"])
    game["music_button"] = QPushButton("Music on")
    game["music_button"].setCheckable(True)
    game["music_button"].setChecked(True)
    game["music_button"].toggled.connect(lambda enabled: toggle_music(game, enabled))
    top.addWidget(game["music_button"])
    reload_button = QPushButton("Reload")
    reload_button.setToolTip("Reload viewer")
    reload_button.clicked.connect(lambda: reload(game))
    top.addWidget(reload_button)
    return top


def build_hud(game):
    game["location"] = label("Waiting for Street View", "location")
    game["location"].setWordWrap(True)
    game["location"].setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    game["heading"] = label("—", "heading")
    game["heading"].setAlignment(Qt.AlignmentFlag.AlignCenter)
    game["gear"] = label("N", "gear")
    game["gear"].setAlignment(Qt.AlignmentFlag.AlignCenter)
    game["gear"].setToolTip("Drive gear: N neutral, D forward, R reverse")
    game["direction"] = label("Route —", "direction")
    game["direction"].setWordWrap(True)
    game["direction"].setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    data = QHBoxLayout()
    data.setSpacing(18)
    data.addWidget(game["location"], stretch=3)
    data.addWidget(game["gear"])
    data.addWidget(game["heading"])
    data.addWidget(game["direction"], stretch=2)
    game["status"] = label("", "status")
    game["status"].setWordWrap(True)
    hints = QHBoxLayout()
    hints.setSpacing(10)
    for binding, action in (MOCK_HINTS if game["mock"] else CONTROLLER_HINTS):
        key = label(binding, "binding")
        caption = label(action, "hint")
        for widget in (key, caption):
            widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        control = QVBoxLayout()
        control.setSpacing(3)
        control.addWidget(key)
        control.addWidget(caption)
        hints.addLayout(control)
    hints.addStretch()

    bottom = QVBoxLayout()
    bottom.setContentsMargins(18, 10, 18, 12)
    bottom.setSpacing(6)
    bottom.addLayout(data)
    bottom.addLayout(hints)
    bottom.addWidget(game["status"])
    hud = QFrame()
    hud.setObjectName("hud")
    hud.setLayout(bottom)
    return hud


def play_sound(game, cue):
    if game["sound_button"].isChecked():
        game["sounds"][cue].play()


def toggle_music(game, enabled):
    game["music_button"].setText("Music on" if enabled else "Music off")
    if enabled and game["viewer_ready"]:
        game["music"].play()
    else:
        game["music"].stop()


def show_map(game):
    if game["viewer_ready"] and not game["map_open"] and game["nav"]["pending"] is None:
        on_map_toggled(game, True)
        play_sound(game, "select")
        game["view"].setFocus()
        game["bridge"].openMap.emit()


def on_map_toggled(game, opened):
    if game["map_open"] and not opened:
        game["wait_for_stick_center"] = True
    game["map_open"] = opened
    game["pressed"].clear()
    game["map_button"].setEnabled(game["viewer_ready"] and not opened)


def on_location_changed(game, state):
    game["nav"] = new_navigation()
    update_state(game, state)
    game["status"].setText("New location loaded.")
    play_sound(game, "arrive")


def reload(game):
    game["pressed"].clear()
    game["nav"] = new_navigation()
    game["viewer_ready"] = False
    on_map_toggled(game, False)
    game["location"].setText("Waiting for Street View")
    game["heading"].setText("—")
    game["gear"].setText("N")
    game["direction"].setText("Route —")
    game["status"].setText("Loading Street View…")
    game["startup_timer"].start()
    game["view"].load(game["url"])
    game["view"].setFocus()


def on_page_loaded(game, ok):
    if not ok:
        on_viewer_failure(game, "Could not open the embedded viewer. Try reloading it.")


def on_viewer_failure(game, message):
    game["startup_timer"].stop()
    game["viewer_ready"] = False
    on_map_toggled(game, False)
    game["nav"] = new_navigation()
    game["location"].setText("Street View unavailable")
    game["heading"].setText("—")
    game["gear"].setText("N")
    game["direction"].setText("Route —")
    game["status"].setText(message)


def update_state(game, state):
    nav = game["nav"]
    pano = state.get("pano")
    heading = state.get("heading")
    if not isinstance(heading, (int, float)) or not isfinite(heading):
        return
    if not can_update(nav, pano):
        return

    routes = []
    for link in state.get("routes") or []:
        angle = link.get("heading")
        if link.get("pano") and isinstance(angle, (int, float)) and isfinite(angle):
            routes.append(make_route(link["pano"], angle % 360, link.get("description") or ""))
    update_navigation(nav, pano, heading, routes)
    if not game["viewer_ready"]:
        game["startup_timer"].stop()
        game["viewer_ready"] = True
        game["map_button"].setEnabled(not game["map_open"])
        if game["music_button"].isChecked() and not game["music"].isPlaying():
            game["music"].play()
        game["status"].setText("Controls paused." if game["paused"] else "Ready.")
    game["location"].setText(state.get("location") or "Unknown location")
    heading = nav["heading"]
    direction_index = int((heading + 22.5) / 45) % len(COMPASS_DIRECTIONS)
    cardinal = COMPASS_DIRECTIONS[direction_index]
    game["heading"].setText(f"{cardinal}   {round(heading) % 360:03d}°")
    update_direction(game)


def update_direction(game):
    nav = game["nav"]
    selected = selected_route(nav)
    ahead = forward_route(nav["heading"], nav["routes"])
    if selected:
        text = f"Selected · {route_label(selected)}"
    elif ahead:
        text = f"Ahead · {route_label(ahead)}"
    elif nav["routes"]:
        text = "Turn toward a route"
    else:
        text = "No routes"
    game["direction"].setText(text)


def on_move(game, error, state):
    nav = game["nav"]
    if nav["pending"] is None:
        return
    pano = "" if error else state.get("pano", "")
    moved = finish_move(nav, pano)
    game["gear"].setText("N")
    update_state(game, state)
    game["map_button"].setEnabled(game["viewer_ready"] and not game["map_open"])
    if moved:
        count = len(nav["history"])
        text = f"Moved · {count} in history"
    else:
        text = error or "The requested panorama is unavailable."
    game["status"].setText(text)
    play_sound(game, "move" if moved else "blocked")


def on_key(game, key, pressed):
    if not key:  # The viewer lost focus before it received key releases.
        game["pressed"].clear()
    elif pressed:
        game["pressed"].add(key)
    else:
        game["pressed"].discard(key)


def clear_keys(game, state):
    if state != Qt.ApplicationState.ApplicationActive:
        game["pressed"].clear()
        map_input(game["mock_input_state"], None)


def mock_input(game):
    keys = game["pressed"]
    buttons = set()
    for key, action in MOCK_BUTTONS.items():
        if key in keys:
            buttons.add(action)

    raw = raw_input(
        left_x=("l" in keys) - ("j" in keys),
        right_x=("arrowright" in keys) - ("arrowleft" in keys),
        right_y=("arrowdown" in keys) - ("arrowup" in keys),
        buttons=buttons,
    )
    return map_input(game["mock_input_state"], raw)


def poll(game):
    now = monotonic()
    elapsed = min(now - game["last_poll"], 0.05)
    game["last_poll"] = now
    if game["mock"]:
        sample = mock_input(game)
        connection = "Keyboard controller"
    elif game["reader"] is not None:
        sample = poll_controller(game["reader"])
        connection = game["reader"]["name"] or "Controller disconnected"
    else:
        game["connection"].setText(game["controller_error"])
        return

    actions = sample["actions"]
    if not game["map_open"] and "pause" in actions:
        game["paused"] = not game["paused"]
        if game["viewer_ready"]:
            game["status"].setText("Controls paused." if game["paused"] else "Controls resumed.")
        play_sound(game, "select")
        if not game["paused"]:
            game["bridge"].requestState.emit()

    connection += f'  ·  Sensitivity {game["sensitivity"]:.2f}×'
    if game["paused"]:
        connection += "  ·  Paused"
    if game["connection"].text() != connection:
        game["connection"].setText(connection)
    if game["map_open"]:
        handle_map_input(game, sample, elapsed)
        return
    if "map" in actions:
        show_map(game)
        return
    if game["paused"] or "pause" in actions:
        return

    if "faster" in actions or "slower" in actions:
        change = 0.25 * (("faster" in actions) - ("slower" in actions))
        game["sensitivity"] = max(0.25, min(3.0, game["sensitivity"] + change))

    if not game["viewer_ready"] or game["nav"]["pending"] is not None:
        return
    handle_driving_input(game, sample, now, elapsed)


def handle_map_input(game, sample, elapsed: float):
    for button, command in MAP_ACTIONS:
        if button in sample["actions"]:
            game["bridge"].mapAction.emit(command)
            return

    x, y = sample["stick"]
    if x or y:
        game["bridge"].panMap.emit(x * 520 * elapsed, y * 520 * elapsed)


def handle_driving_input(game, sample, now: float, elapsed: float):
    nav = game["nav"]
    actions = sample["actions"]
    if "next" in actions or "previous" in actions:
        step = 1 if "next" in actions else -1
        route = select_direction(nav, step)
        update_direction(game)
        game["status"].setText("Press ✕ or Enter to confirm." if route else "No connected routes here.")
        play_sound(game, "select" if route else "blocked")

    if not any(sample["stick"]):
        game["wait_for_stick_center"] = False
    drive = sample["drive"]
    if drive and not game["wait_for_stick_center"]:
        just_pressed = f"drive_{drive}" in actions
        if just_pressed or can_repeat_drive(nav, drive, now):
            actions = actions | {drive}

    # Process at most one movement action per poll, even if both triggers fire.
    for action in ("back", "confirm", "forward"):
        if action in actions:
            movement, message = start_move(nav, action)
            game["status"].setText(message)
            if movement is not None:
                game["gear"].setText("R" if movement["backward"] else "D")
                game["map_button"].setEnabled(False)
                game["bridge"].navigate.emit(movement["target"])
            else:
                play_sound(game, "blocked")
            return

    x, y = sample["camera"]
    if x or y:
        speed = game["sensitivity"] * elapsed
        game["bridge"].rotateCamera.emit(x * 110 * speed, -y * 75 * speed)


def can_repeat_drive(nav, drive, now):
    if now - nav["last_move"] < DRIVE_REPEAT_INTERVAL:
        return False
    if drive == "back":
        return bool(nav["history"])
    return forward_route(nav["heading"], nav["routes"]) is not None


def coordinates(value: str) -> tuple[float, float]:
    try:
        latitude, longitude = map(float, value.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError(f"use LAT,LNG, for example {START[0]},{START[1]}") from None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise argparse.ArgumentTypeError("latitude must be ±90 and longitude must be ±180")
    return latitude, longitude


def main() -> int:
    parser = argparse.ArgumentParser(description="Explore Google Street View with a DualSense.")
    parser.add_argument("--mock-controller", action="store_true", help="use the keyboard as a controller")
    parser.add_argument("--start", type=coordinates, default=START, metavar="LAT,LNG",
                        help="starting coordinates (default: Chulalongkorn University, Bangkok)")
    parser.add_argument("--port", type=int, default=PORT, help="local viewer port (default: 8765)")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("--port must be between 1024 and 65535")

    name = application_name()
    app = QApplication([sys.argv[0]])
    app.setApplicationName(name)
    try:
        key = load_settings()
        server = serve_viewer(args.port)
    except (OSError, UnicodeError) as error:
        QMessageBox.critical(None, name, f"Could not start the local viewer.\n{error}")
        return 1
    with server:
        try:
            game = create_game(name, key, args.start, args.port, args.mock_controller)
            game["window"].show()
            try:
                return app.exec()
            finally:
                stop_game(game)
        finally:
            server.shutdown()


if __name__ == "__main__":
    sys.exit(main())
