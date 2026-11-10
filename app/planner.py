"""TrailTrain planner: turns a route timetable + everyone's inputs into a plan.

Rules only, no AI model: every time in the plan comes from route.json
(or from a simulated delay), so each line can be traced to its source.
"""

FITNESS_ORDER = ["strong", "moderate", "easy"]  # later = slower


def to_min(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def to_hhmm(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _source(route, train_id=None, delay=0):
    src = f"{route['data_source']} · data date {route['data_date']}"
    if train_id:
        src = f"{train_id} · " + src
    if delay:
        src += f" · +{delay} min simulated delay"
    return src


def make_plan(route, friends, earliest_departure="08:30", delays=None):
    """Build a plan for the group.

    friends: list of {"name", "station", "fitness", "budget"}
    delays: {outbound_train_id: minutes}, applied to every stop of that train
    Returns a dict; "ok" is False when no plan fits.
    """
    delays = delays or {}
    if not friends:
        return {"ok": False, "reason": "No one has joined yet."}

    walk = route["walk_station_to_trailhead_min"]
    buffer = route["safety_buffer_min"]
    sunset = to_min(route["sunset"])
    dest = route["destination"]

    # 1. Merge constraints: slowest fitness sets the hike length.
    slowest = max(friends, key=lambda f: FITNESS_ORDER.index(f["fitness"]))
    hike = route["hike_minutes"][slowest["fitness"]]

    warnings = []
    for f in friends:
        fare = 2 * route["fares_one_way"][f["station"]]
        if f["budget"] < fare:
            warnings.append(
                f"{f['name']}: budget ${f['budget']:.0f} is below the round-trip fare ${fare:.0f}."
            )

    # Everyone rides the same train; the group is complete at the
    # boarding station the train reaches last.
    station_order = route["stations"]
    last_board = max((f["station"] for f in friends), key=station_order.index)
    first_board = min((f["station"] for f in friends), key=station_order.index)

    # 2. Find outbound trains that leave after the earliest departure and
    #    still let the slowest person get off the trail before sunset.
    candidates = []
    for t in route["outbound"]:
        d = delays.get(t["id"], 0)
        board = to_min(t["stops"][first_board]) + d
        if board < to_min(earliest_departure):
            continue
        arrive = to_min(t["stops"][dest]) + d
        trail_start = arrive + walk
        trail_end = trail_start + hike
        if trail_end > sunset - buffer:
            continue
        candidates.append((board, t, d, arrive, trail_start, trail_end))
    candidates.sort(key=lambda c: c[0])

    if not candidates:
        return {
            "ok": False,
            "reason": "No train gets the group off the trail before sunset. Try an earlier start or a shorter hike.",
            "warnings": warnings,
        }

    # 3. Work back from the last train home.
    last_return = route["return"][-1]
    latest_by_train = to_min(last_return["stops"][dest]) - walk - buffer
    latest_by_sunset = sunset - buffer
    latest_off_trail = min(latest_by_train, latest_by_sunset)
    binding = "sunset" if latest_by_sunset <= latest_by_train else "last train"

    def build_option(c):
        board, t, d, arrive, trail_start, trail_end = c
        ready = trail_end + walk
        ret = next((r for r in route["return"] if to_min(r["stops"][dest]) >= ready), None)
        boarding = [
            {
                "name": f["name"],
                "station": f["station"],
                "time": to_hhmm(to_min(t["stops"][f["station"]]) + d),
            }
            for f in friends
        ]
        return {
            "train": t["id"],
            "delay_min": d,
            "boarding": boarding,
            "meeting_point": (
                f"Front car of {t['id']}; the last person boards at {last_board} "
                f"at {to_hhmm(to_min(t['stops'][last_board]) + d)}."
            ),
            "arrive": to_hhmm(arrive),
            "trail_start": to_hhmm(trail_start),
            "trail_end": to_hhmm(trail_end),
            "return_train": ret["id"] if ret else None,
            "return_departs": ret["stops"][dest] if ret else None,
            "home": [
                {"name": f["name"], "station": f["station"], "time": ret["stops"][f["station"]]}
                for f in friends
            ] if ret else [],
            "source": _source(route, t["id"], d),
        }

    main = build_option(candidates[0])
    backup = build_option(candidates[1]) if len(candidates) > 1 else None

    return {
        "ok": True,
        "route": route["name"],
        "hike_minutes": hike,
        "hike_set_by": f"{slowest['name']} ({slowest['fitness']})",
        "main": main,
        "backup": backup,
        "last_train_home": last_return["stops"][dest],
        "last_train_id": last_return["id"],
        "latest_off_trail": to_hhmm(latest_off_trail),
        "latest_off_trail_reason": binding,
        "sunset": route["sunset"],
        "warnings": warnings,
        "data_status": route["data_status"],
        "source": _source(route),
    }


def describe_change(old, new):
    """One-line notification when the main plan changed, else None."""
    if not old or not new or not old.get("ok") or not new.get("ok"):
        if old and old.get("ok") and new and not new.get("ok"):
            return f"Plan no longer works: {new['reason']}"
        return None
    o, n = old["main"], new["main"]
    if (o["train"], o["arrive"], o["return_train"]) == (n["train"], n["arrive"], n["return_train"]):
        return None
    return (
        f"Re-planned: take {n['train']} (arrives {n['arrive']}), on trail {n['trail_start']}–{n['trail_end']}, "
        f"home on {n['return_train']} at {n['return_departs']}. Off trail by {new['latest_off_trail']}."
    )
