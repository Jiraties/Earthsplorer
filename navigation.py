"""Choose routes and remember successfully visited panoramas."""

from time import monotonic

MAX_FORWARD_ANGLE = 60
MOVE_COOLDOWN = 0.4


def new_navigation():
    return {
        "pano": "",
        "heading": 0,
        "routes": [],
        "selection": "",
        "history": [],
        "pending": None,
        "last_move": float("-inf"),
    }


def angular_difference(first, second):
    # Wrap around north so the result is between 0 and 180 degrees.
    return abs((first - second + 180) % 360 - 180)


def make_route(pano, heading, description=""):
    return {"pano": pano, "heading": heading, "description": description}


def route_label(route):
    degrees = round(route["heading"]) % 360
    if route["description"]:
        return f'{route["description"]} · {degrees:03d}°'
    return f"{degrees:03d}°"


def forward_route(heading, routes):
    closest = None
    smallest_gap = float("inf")
    for route in routes:
        gap = angular_difference(heading, route["heading"])
        if gap < smallest_gap:
            closest = route
            smallest_gap = gap
    if smallest_gap <= MAX_FORWARD_ANGLE:
        return closest
    return None


def can_update(nav, pano):
    # Only the currently confirmed panorama may update the driving controls.
    return bool(pano) and nav["pending"] is None and nav["pano"] in ("", pano)


def update_navigation(nav, pano, heading, routes):
    if not can_update(nav, pano):
        return
    nav["pano"] = pano
    nav["heading"] = heading % 360

    routes_by_pano = {}
    for route in routes:
        if route["pano"] and route["pano"] != pano:
            routes_by_pano[route["pano"]] = route
    nav["routes"] = sorted(routes_by_pano.values(), key=route_order)
    if selected_route(nav) is None:
        nav["selection"] = ""


def route_order(route):
    return route["heading"], route["pano"]


def selected_route(nav):
    for route in nav["routes"]:
        if route["pano"] == nav["selection"]:
            return route
    return None


def select_direction(nav, step):
    routes = nav["routes"]
    if nav["pending"] is not None or not routes:
        return None

    selected = selected_route(nav)
    if selected is None:
        # The first flick starts from the camera heading.
        closest_distance = 360
        for route in routes:
            distance = (step * (route["heading"] - nav["heading"])) % 360
            if distance < closest_distance:
                selected = route
                closest_distance = distance
    else:
        index = (routes.index(selected) + step) % len(routes)
        selected = routes[index]

    nav["selection"] = selected["pano"]
    return selected


def start_move(nav, action):
    if not nav["pano"]:
        return None, "Street View is unavailable."
    if nav["pending"] is not None:
        return None, "Moving…"
    if monotonic() - nav["last_move"] < MOVE_COOLDOWN:
        return None, "Wait for the panorama to settle."

    if action == "back":
        if not nav["history"]:
            return None, "No previous panorama."
        target = nav["history"][-1]
    else:
        if action == "confirm":
            route = selected_route(nav)
        else:
            route = forward_route(nav["heading"], nav["routes"])

        if route is None:
            if not nav["routes"]:
                return None, "No connected routes here."
            if action == "confirm":
                return None, "Flick the left stick sideways to select a route."
            return None, "Turn toward a route or select one with the left stick."
        target = route["pano"]

    movement = {"target": target, "backward": action == "back"}
    nav["pending"] = movement
    return movement, "Moving…"


def finish_move(nav, pano):
    movement = nav["pending"]
    if movement is None:
        return False

    nav["pending"] = None
    nav["last_move"] = monotonic()
    if pano != movement["target"]:
        return False

    # Change history only when Street View confirms the arrival.
    if movement["backward"]:
        nav["history"].pop()
    else:
        nav["history"].append(nav["pano"])
    nav["pano"] = pano
    nav["routes"] = []
    nav["selection"] = ""
    return True
