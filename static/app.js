"use strict";

const canvas = document.querySelector("#panorama");
const message = document.querySelector("#message");
const locations = document.querySelector("#locations");
const mapStatus = document.querySelector("#map-status");
const mapCanvas = document.querySelector("#world-map");
const mapStage = document.querySelector("#map-stage");
const placeSearch = document.querySelector("#place-search");
const placeQuery = document.querySelector("#place-query");
const presets = [...document.querySelectorAll(".presets button[data-lat]")];
const driveHere = document.querySelector("#drive-here");
let bridge;
let panorama;
let locationMap;
let activeSearch = null;
let currentPano = "";
let currentLinks = [];
let lookup = null;
let timeout;
let frame;
let disabled = false;

function fail(messageText) {
    clearTimeout(timeout);
    disabled = true;
    message.textContent = messageText;
    message.hidden = false;
    if (locations.open) {
        locations.close();
    }
    bridge?.reportError(messageText);
}

function snapshot() {
    const position = panorama.getPosition();
    const location = panorama.getLocation();
    return {
        pano: currentPano,
        heading: panorama.getPov().heading,
        location: location?.description ||
            (position ? position.toUrlValue(5) : "Unknown location"),
        routes: currentLinks
            .filter(link => link?.pano && Number.isFinite(link.heading))
            .map(({ pano, heading, description }) => ({ pano, heading, description })),
    };
}

function publishState() {
    if (disabled || lookup || !currentPano || panorama.getPano() !== currentPano) {
        return;
    }
    bridge.reportState(snapshot());
}

function scheduleState() {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(publishState);
}

function beginLookup(kind, target, pov, error = "") {
    lookup = { kind, target, pov, error, links: null, previousPov: panorama.getPov() };
    timeout = setTimeout(() => fail("Street View timed out. Reload the viewer to try again."), 12000);
    if (kind === "start") {
        panorama.setPosition(target);
    } else {
        panorama.setPano(target);
    }
}

function onLookupStatus() {
    const request = lookup;
    if (disabled || !request) {
        return;
    }

    clearTimeout(timeout);
    lookup = null;

    const pano = panorama.getPano();
    const successful = panorama.getStatus() === google.maps.StreetViewStatus.OK && pano &&
        (request.kind === "start" || pano === request.target);
    if (!successful) {
        if (request.kind === "move" || request.kind === "jump") {
            // A failed lookup can leave Google's viewer on an invalid panorama.
            // Restore the last confirmed view before accepting another movement.
            const restore = request.kind === "jump" ? "restoreJump" : "restore";
            beginLookup(restore, currentPano, request.previousPov, "The requested panorama is unavailable.");
        } else if (request.kind === "start") {
            fail("No Street View panorama loaded at the starting coordinates. Check your connection or choose another start.");
        } else {
            fail("Street View could not restore the previous panorama. Reload the viewer to continue.");
        }
        return;
    }

    currentLinks = request.links ?? (pano === currentPano ? currentLinks : []);
    currentPano = pano;
    panorama.setPov(request.pov);
    if (request.kind === "start") {
        message.hidden = true;
        publishState();
    } else if (request.kind === "jump") {
        bridge.reportJump(snapshot());
        locations.close();
    } else if (request.kind === "restoreJump") {
        mapStatus.textContent = request.error;
    } else {
        bridge.reportMove(request.error, snapshot());
    }
}

function startViewer(start, heading) {
    panorama = new google.maps.StreetViewPanorama(canvas, {
        addressControl: false,
        clickToGo: false,
        disableDefaultUI: true,
        keyboardShortcuts: false,
        linksControl: false,
        motionTracking: false,
        motionTrackingControl: false,
        visible: true,
    });

    panorama.addListener("status_changed", onLookupStatus);
    panorama.addListener("pov_changed", scheduleState);
    panorama.addListener("position_changed", scheduleState);
    panorama.addListener("links_changed", () => {
        // pano_changed by itself does not mean the new panorama's links are ready.
        const links = panorama.getLinks() ?? [];
        if (lookup) {
            lookup.links = links;
        } else if (panorama.getPano() === currentPano) {
            currentLinks = links;
        }
        scheduleState();
    });
    new ResizeObserver(() => google.maps.event.trigger(panorama, "resize")).observe(canvas);

    bridge.rotateCamera.connect((headingDelta, pitchDelta) => {
        if (disabled || lookup || !currentPano) {
            return;
        }
        const { heading, pitch } = panorama.getPov();
        panorama.setPov({
            heading: ((heading + headingDelta) % 360 + 360) % 360,
            pitch: Math.max(-85, Math.min(85, pitch + pitchDelta)),
        });
    });
    bridge.navigate.connect(target => {
        if (!disabled && !lookup && currentPano) {
            beginLookup("move", target, panorama.getPov());
        }
    });
    bridge.requestState.connect(publishState);
    bridge.openMap.connect(showMap);
    bridge.panMap.connect(panMap);
    bridge.mapAction.connect(controlMap);
    beginLookup("start", start, { heading, pitch: 0 });
}

function panMap(x, y) {
    if (!locations.open || lookup || activeSearch || !locationMap) {
        return;
    }
    const projection = locationMap.getProjection();
    const center = locationMap.getCenter();
    if (!projection || !center) {
        return;
    }
    // Convert screen pixels to zoom-independent world coordinates.
    // moveCamera applies each stick sample immediately without queuing an animation.
    const scale = 2 ** locationMap.getZoom();
    const point = projection.fromLatLngToPoint(center);
    const next = new google.maps.Point(point.x + x / scale,
        Math.max(0, Math.min(256, point.y + y / scale)));
    locationMap.moveCamera({ center: projection.fromPointToLatLng(next) });
}

async function showMap() {
    if (disabled || lookup || !currentPano || locations.open) {
        return;
    }
    locations.showModal();
    bridge.reportMap(true);
    mapStage.hidden = false;
    driveHere.hidden = false;
    mapStatus.textContent = "Click a road on the map or pick a preset.";
    try {
        if (!locationMap) {
            const { Map } = await google.maps.importLibrary("maps");
            if (!locations.open) {
                return;
            }
            locationMap = new Map(mapCanvas, {
                zoom: 15,
                center: panorama.getPosition(),
                streetViewControl: false,
                fullscreenControl: false,
                mapTypeControl: false,
                clickableIcons: false,
            });
            locationMap.addListener("click", event => chooseLocation(event.latLng));
        } else {
            locationMap.setCenter(panorama.getPosition());
        }
    } catch {
        mapStage.hidden = true;
        driveHere.hidden = true;
        mapStatus.textContent = "The map could not load. Choose a preset below.";
    }
}

function controlMap(action) {
    if (!locations.open || lookup) {
        return;
    }
    if (action === "close") {
        locations.close();
    } else if (action === "drop" && !mapStage.hidden) {
        const center = locationMap?.getCenter();
        if (center) {
            chooseLocation(center);
        }
    } else if (locationMap && (action === "in" || action === "out")) {
        const zoom = locationMap.getZoom() + (action === "in" ? 1 : -1);
        locationMap.setZoom(Math.min(20, Math.max(2, zoom)));
    }
}

function presetPosition(button) {
    return { lat: Number(button.dataset.lat), lng: Number(button.dataset.lng) };
}

function previewPlace(position) {
    if (!locationMap || mapStage.hidden) {
        chooseLocation(position);
        return;
    }
    locationMap.setCenter(position);
    locationMap.setZoom(17);
    mapStatus.textContent = "Adjust the map to a road and press ✕, or click a road.";
}

function startMapSearch(status, timeoutMessage) {
    mapStatus.textContent = status;
    const search = {};
    activeSearch = search;
    search.timer = setTimeout(() => {
        if (activeSearch === search) {
            finishMapSearch(search);
            mapStatus.textContent = timeoutMessage;
        }
    }, 8000);
    return search;
}

function finishMapSearch(search) {
    clearTimeout(search.timer);
    if (activeSearch === search) {
        activeSearch = null;
    }
}

async function searchForPlace(event) {
    event.preventDefault();
    if (activeSearch || lookup) {
        return;
    }
    const query = placeQuery.value.trim();
    if (!query) {
        return;
    }
    placeQuery.blur();
    const preset = presets.find(button => button.textContent.toLowerCase().includes(query.toLowerCase()));
    if (preset) {
        previewPlace(presetPosition(preset));
        return;
    }
    const coordinates = query.match(/^([-+]?\d+(?:\.\d+)?)\s*,\s*([-+]?\d+(?:\.\d+)?)$/);
    if (coordinates) {
        const [, lat, lng] = coordinates.map(Number);
        if (Math.abs(lat) <= 90 && Math.abs(lng) <= 180) {
            previewPlace({ lat, lng });
        } else {
            mapStatus.textContent = "Enter latitude between −90 and 90 and longitude between −180 and 180.";
        }
        return;
    }

    const search = startMapSearch(
        "Searching for the place…",
        "Place search timed out. Try again or use coordinates.",
    );
    try {
        const { Geocoder } = await google.maps.importLibrary("geocoding");
        const { results } = await new Geocoder().geocode({
            address: query, bounds: locationMap?.getBounds(),
        });
        if (activeSearch === search) {
            const position = results[0].geometry.location;
            finishMapSearch(search);
            previewPlace(position);
        }
    } catch (error) {
        if (activeSearch === search) {
            mapStatus.textContent = error?.code === "REQUEST_DENIED"
                ? "Enable Geocoding API for this key, or search by coordinates or preset."
                : "Place not found. Try a more specific address or use coordinates.";
        }
    } finally {
        finishMapSearch(search);
    }
}

function firstRoad(panoramaData) {
    return panoramaData.links?.find(link => link?.pano && Number.isFinite(link.heading));
}

async function chooseLocation(location) {
    if (!locations.open || activeSearch || lookup) {
        return;
    }
    const search = startMapSearch(
        "Checking nearby Street View…",
        "The search timed out. Choose a spot to retry.",
    );
    try {
        const service = new google.maps.StreetViewService();
        const { StreetViewPreference, StreetViewSource } = google.maps;
        const sources = [StreetViewSource.GOOGLE, StreetViewSource.OUTDOOR];
        let { data } = await service.getPanorama({
            location, radius: 50, sources, preference: StreetViewPreference.NEAREST,
        });
        if (activeSearch === search && !firstRoad(data)) {
            // A nearby points-of-interest panorama can lack road connections.
            ({ data } = await service.getPanorama({
                location, radius: 80, sources, preference: StreetViewPreference.BEST,
            }));
        }
        if (activeSearch !== search) {
            return;
        }
        const target = data.location?.pano;
        const road = firstRoad(data);
        if (!target || !road) {
            mapStatus.textContent = "No connected panorama here. Try a nearby road.";
            return;
        }
        const pov = { heading: road.heading, pitch: 0 };
        if (target === currentPano) {
            panorama.setPov(pov);
            locations.close();
        } else {
            mapStatus.textContent = "Loading the new location…";
            beginLookup("jump", target, pov);
        }
    } catch {
        if (activeSearch === search) {
            mapStatus.textContent = "No Street View loaded here. Try another road or preset.";
        }
    } finally {
        finishMapSearch(search);
    }
}

document.querySelector("#close-map").addEventListener("click", () => {
    if (!lookup) {
        locations.close();
    }
});
placeSearch.addEventListener("submit", searchForPlace);
driveHere.addEventListener("click", () => controlMap("drop"));
locations.addEventListener("cancel", event => {
    if (lookup) {
        event.preventDefault();
    }
});
locations.addEventListener("close", () => {
    if (activeSearch) {
        finishMapSearch(activeSearch);
    }
    bridge.reportMap(false);
});
for (const preset of presets) {
    preset.addEventListener("click", () => chooseLocation(presetPosition(preset)));
}

function connectKeyboard(keys) {
    const controls = new Set(keys);
    for (const type of ["keydown", "keyup"]) {
        window.addEventListener(type, event => {
            const key = event.key.toLowerCase();
            const shortcut = type === "keydown" && (event.metaKey || event.ctrlKey || event.altKey);
            if (!locations.open && controls.has(key) && !shortcut) {
                event.preventDefault();
                event.stopImmediatePropagation();
                if (!event.repeat) {
                    bridge.reportKey(key, type === "keydown");
                }
            }
        }, true);
    }
    window.addEventListener("blur", () => bridge.reportKey("", false));
}

function loadMaps({ key, start, heading, mockKeys }) {
    if (mockKeys.length) {
        connectKeyboard(mockKeys);
    }
    if (!key) {
        fail("Add GOOGLE_MAPS_API_KEY to .env and restart Earthsplorer.");
        return;
    }

    message.textContent = "Loading Google Street View…";
    window.gm_authFailure = () => fail("Google rejected the Maps API key. Check billing, API access, and the allowed referrer.");
    window.earthsplorerMapsReady = () => {
        clearTimeout(timeout);
        if (!disabled) {
            startViewer(start, heading);
        }
    };

    const params = new URLSearchParams({
        key,
        v: "quarterly",
        libraries: "streetView",
        loading: "async",
        callback: "earthsplorerMapsReady",
        auth_referrer_policy: "origin",
    });
    const script = document.createElement("script");
    script.src = "https://maps.googleapis.com/maps/api/js?" + params;
    script.async = true;
    script.onerror = () => fail("Google Maps could not be reached. Check your internet connection and reload the viewer.");
    timeout = setTimeout(() => fail("Google Maps took too long to load. Reload the viewer to try again."), 15000);
    document.head.append(script);
}

if (window.qt && typeof QWebChannel !== "undefined") {
    new QWebChannel(qt.webChannelTransport, channel => {
        bridge = channel.objects.viewer;
        bridge.settings(loadMaps);
    });
} else {
    fail("Open this viewer from the Earthsplorer desktop app.");
}
