"""Read the controller and turn stick or button input into game actions."""

import os
from math import hypot
from time import monotonic

# SDL2's mapped touchpad button. Pygame 2.6 does not export the name.
SDL_BUTTON_TOUCHPAD = 20
PRESS_THRESHOLD = 0.60
RELEASE_THRESHOLD = 0.35
SCAN_INTERVAL = 0.5


def normalize_axis(value):
    limit = 32768 if value < 0 else 32767
    return max(-1.0, min(1.0, value / limit))


def normalize_trigger(value):
    # SDL's mapped triggers report zero at rest.
    return max(0.0, min(1.0, value / 32767))


def apply_dead_zone(x, y, dead_zone=0.15):
    distance = hypot(x, y)
    if distance <= dead_zone:
        return 0.0, 0.0

    # Remove the dead zone and scale the rest of the stick travel to full speed.
    usable_travel = min(distance, 1.0) - dead_zone
    scale = usable_travel / ((1.0 - dead_zone) * distance)
    return x * scale, y * scale


def raw_input(left_x=0, left_y=0, right_x=0, right_y=0, forward=0, back=0, buttons=()):
    return {
        "left_x": left_x,
        "left_y": left_y,
        "right_x": right_x,
        "right_y": right_y,
        "forward": forward,
        "back": back,
        "buttons": buttons,
    }


def idle_input():
    return {"camera": (0, 0), "actions": set(), "stick": (0, 0), "drive": ""}


def new_input_state():
    return {"held": None, "wait_for_drive_release": True}


def map_input(state, raw):
    if raw is None:
        state["held"] = None
        state["wait_for_drive_release"] = True
        return idle_input()

    held = set(raw["buttons"])
    previous = state["held"] or set()

    # Use the strongest axis so a diagonal input does one thing at a time.
    sideways = raw["left_x"]
    vertical = raw["left_y"]
    if abs(sideways) > abs(vertical):
        vertical = 0
    else:
        sideways = 0

    analog_actions = {
        "forward": raw["forward"],
        "back": raw["back"],
        "next": sideways,
        "previous": -sideways,
        "drive_forward": -vertical,
        "drive_back": vertical,
    }
    for action, value in analog_actions.items():
        if action in previous:
            threshold = RELEASE_THRESHOLD
        else:
            threshold = PRESS_THRESHOLD
        if value >= threshold:
            held.add(action)

    # A held button only fires once. Ignore buttons already held on connection.
    actions = set()
    if state["held"] is not None:
        actions = held - previous
    state["held"] = held

    drive = ""
    if "drive_forward" in held:
        drive = "forward"
    elif "drive_back" in held:
        drive = "back"
    if state["wait_for_drive_release"]:
        state["wait_for_drive_release"] = bool(drive)
        drive = ""

    return {
        "camera": apply_dead_zone(raw["right_x"], raw["right_y"]),
        "actions": actions,
        "stick": apply_dead_zone(raw["left_x"], raw["left_y"]),
        "drive": drive,
    }


def open_controller():
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")
    # Pygame needs a video driver to pump events. Qt draws the actual window.
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    import pygame
    from pygame._sdl2 import controller

    try:
        pygame.display.init()
        controller.init()
    except pygame.error:
        pygame.quit()
        raise

    return {
        "pygame": pygame,
        "sdl": controller,
        "device": None,
        "name": "",
        "next_scan": 0,
        "input": new_input_state(),
    }


def find_controller(reader):
    sdl = reader["sdl"]
    first_gamepad = None
    for index in range(sdl.get_count()):
        if not sdl.is_controller(index):
            continue
        name = sdl.name_forindex(index) or "Gamepad"
        device = (index, name)
        if first_gamepad is None:
            first_gamepad = device
        lower_name = name.lower()
        if "dualsense" in lower_name or "ps5" in lower_name or "wireless controller" in lower_name:
            return device
    return first_gamepad


def poll_controller(reader):
    pygame = reader["pygame"]
    try:
        pygame.event.get()
        if reader["device"] is not None and not reader["device"].attached():
            disconnect_controller(reader)

        now = monotonic()
        if reader["device"] is None and now >= reader["next_scan"]:
            reader["next_scan"] = now + SCAN_INTERVAL
            candidate = find_controller(reader)
            if candidate is not None:
                index, name = candidate
                reader["device"] = reader["sdl"].Controller(index)
                reader["name"] = name

        if reader["device"] is None:
            return map_input(reader["input"], None)
        raw = read_controller(reader["device"], pygame)
        return map_input(reader["input"], raw)
    except pygame.error:
        # A controller can disconnect in between checks.
        disconnect_controller(reader)
        return idle_input()


def read_controller(device, pygame):
    axis = device.get_axis
    bindings = {
        "confirm": pygame.CONTROLLER_BUTTON_A,
        "cancel": pygame.CONTROLLER_BUTTON_B,
        "map": SDL_BUTTON_TOUCHPAD,
        "pause": pygame.CONTROLLER_BUTTON_START,
        "faster": pygame.CONTROLLER_BUTTON_DPAD_UP,
        "slower": pygame.CONTROLLER_BUTTON_DPAD_DOWN,
    }
    buttons = set()
    for action, code in bindings.items():
        if device.get_button(code):
            buttons.add(action)

    return raw_input(
        left_x=normalize_axis(axis(pygame.CONTROLLER_AXIS_LEFTX)),
        left_y=normalize_axis(axis(pygame.CONTROLLER_AXIS_LEFTY)),
        right_x=normalize_axis(axis(pygame.CONTROLLER_AXIS_RIGHTX)),
        right_y=normalize_axis(axis(pygame.CONTROLLER_AXIS_RIGHTY)),
        forward=normalize_trigger(axis(pygame.CONTROLLER_AXIS_TRIGGERRIGHT)),
        back=normalize_trigger(axis(pygame.CONTROLLER_AXIS_TRIGGERLEFT)),
        buttons=buttons,
    )


def disconnect_controller(reader):
    if reader["device"] is not None:
        reader["device"].quit()
        reader["device"] = None
    reader["name"] = ""
    map_input(reader["input"], None)


def close_controller(reader):
    disconnect_controller(reader)
    reader["pygame"].quit()
