"""Serve the embedded viewer and exchange messages over Qt's WebChannel."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from PySide6.QtCore import QFile, QIODevice, QObject, Signal, Slot

from config import ROOT, START, START_HEADING


def serve_viewer(port: int) -> ThreadingHTTPServer:
    """Give Maps a stable HTTP referrer using a static, loopback-only server."""
    resource = QFile(":/qtwebchannel/qwebchannel.js")
    if not resource.open(QIODevice.OpenModeFlag.ReadOnly):
        raise OSError("Qt's WebChannel JavaScript could not be loaded.")
    webchannel_script = bytes(resource.readAll())
    resource.close()

    assets = {
        "/": ("text/html", (ROOT / "static/index.html").read_bytes()),
        "/app.js": ("text/javascript", (ROOT / "static/app.js").read_bytes()),
        "/style.css": ("text/css", (ROOT / "static/style.css").read_bytes()),
        "/qwebchannel.js": ("text/javascript", webchannel_script),
    }

    class ViewerHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
                self.send_error(400)
                return
            if self.path not in assets:
                self.send_error(404)
                return

            content_type, content = assets[self.path]
            self.send_response(200)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), ViewerHandler)
    Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True).start()
    return server


# WebChannel needs Qt signals and slots to exchange messages with JavaScript.
class ViewerBridge(QObject):
    rotateCamera = Signal(float, float)
    navigate = Signal(str)
    requestState = Signal()
    openMap = Signal()
    panMap = Signal(float, float)
    mapAction = Signal(str)

    state_received = Signal(dict)
    movement_finished = Signal(str, dict)
    viewer_failed = Signal(str)
    key_changed = Signal(str, bool)
    map_toggled = Signal(bool)
    location_changed = Signal(dict)

    def __init__(self, key: str, start: tuple[float, float], mock_keys: list[str], parent: QObject):
        super().__init__(parent)
        self.key = key
        self.start = start
        self.mock_keys = mock_keys

    @Slot(result="QVariantMap")
    def settings(self):
        latitude, longitude = self.start
        heading = START_HEADING if self.start == START else 90
        return {
            "key": self.key,
            "start": {"lat": latitude, "lng": longitude},
            "heading": heading,
            "mockKeys": self.mock_keys,
        }

    @Slot("QVariantMap")
    def reportState(self, state):
        self.state_received.emit(state)

    @Slot(str, "QVariantMap")
    def reportMove(self, error, state):
        self.movement_finished.emit(error, state)

    @Slot(str)
    def reportError(self, message):
        self.viewer_failed.emit(message)

    @Slot(str, bool)
    def reportKey(self, key, pressed):
        self.key_changed.emit(key, pressed)

    @Slot(bool)
    def reportMap(self, opened):
        self.map_toggled.emit(opened)

    @Slot("QVariantMap")
    def reportJump(self, state):
        self.location_changed.emit(state)
