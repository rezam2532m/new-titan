"""Background tasks: traffic flush, housekeeping, keep-alive, auto-backup."""
import asyncio
import base64
import gzip
import logging
import os
import time

import httpx

from . import config, db, state, xray

log = logging.getLogger("titan.tasks")

# Cached Cloudflare colo for the location widget. It is deliberately kept
# separate from the process's authoritative node location below.
LOCATION: dict = {"colo": "?"}
NODE_LOCATION: dict = {}
EDGE_FALLBACK_LOCATION: dict = {}


def _clear_node_location() -> None:
    """Do not expose a location left behind by an older edge-based refresh."""
    NODE_LOCATION.clear()
    EDGE_FALLBACK_LOCATION.clear()
    db.set_local_node_location("", "", "", "🌐")


# usage deltas waiting to be reported back to the main panel (node role)
_pending_usage: dict[str, dict] = {}


async def _periodic_flush():
    """Every 5s pull Xray deltas and add them to each user's usage."""
    global _pending_usage
    while True:
        try:
            await asyncio.sleep(5)
            deltas = await xray.get_xray_stats()
            if deltas:
                total_up = total_down = 0
                cut_off = []
                for uid, d in deltas.items():
                    up, down = d.get("up", 0), d.get("down", 0)
                    db.add_user_usage(uid, up, down)
                    db.touch_last_seen(uid)
                    state.LAST_TRAFFIC[uid] = time.time()
                    total_up += up
                    total_down += down
                    if config.IS_NODE:
                        # report back to the main panel instead of enforcing
                        # quotas locally (the main panel is the authority)
                        p = _pending_usage.setdefault(uid, {"up": 0, "down": 0})
                        p["up"] += up
                        p["down"] += down
                    elif _check_quota(uid):
                        cut_off.append(uid)
                if cut_off:
                    await _apply_cutoffs(cut_off)
                db.add_traffic(int(time.time() // 3600) * 3600, total_up, total_down)
        except asyncio.CancelledError:
            break
        except Exception:  # noqa: BLE001
            await asyncio.sleep(2)


def _check_quota(uid: str) -> bool:
    """Cut a user off once their volume is spent. True when this call did it.

    Marking the row disabled is not enough: Xray keeps serving the credentials
    until the config is rewritten and the process restarted, which is why an
    emptied config used to keep working (and keep burning traffic) until someone
    happened to reload. The caller reloads once per burst.
    """
    user = db.get_user(uid)
    if not user:
        return False
    quota = user["quota_bytes"] or 0
    used = (user["used_up"] or 0) + (user["used_down"] or 0)
    if quota > 0 and used >= quota and user["enabled"]:
        db.update_user(uid, {"enabled": False})
        db.add_event("warn", "auto-disable", f"quota reached: {uid}", user_id=user["id"])
        return True
    return False


async def _apply_cutoffs(uids: list) -> None:
    """Apply the cut-offs to Xray now, and tell the nodes to do the same."""
    if not uids:
        return
    log.warning("volume spent — cutting %d config(s) off now: %s",
                len(uids), ", ".join(uids[:6]))
    try:
        await asyncio.to_thread(xray.write_xray_config)
        await asyncio.to_thread(xray.restart_xray)
    except Exception:  # noqa: BLE001
        log.exception("could not apply the cut-off to xray")
    if not config.IS_NODE:
        try:
            from . import nodes as nodesync
            await nodesync.sync_all()
        except Exception:  # noqa: BLE001
            log.exception("could not push the cut-off to the nodes")


async def _housekeeping():
    """Disable expired users, heartbeat the local node, run backups."""
    while True:
        try:
            await asyncio.sleep(30)
            now = time.time()
            expired_now = []
            for u in db.list_users():
                if u["enabled"] and u.get("expire_at") and now >= u["expire_at"]:
                    db.update_user(u["uid"], {"enabled": False})
                    db.add_event("warn", "auto-disable", f"expired: {u['uid']}", user_id=u["id"])
                    expired_now.append(u["uid"])
            if expired_now:
                await _apply_cutoffs(expired_now)
            # keep the local node's "last seen" fresh
            for n in db.list_nodes():
                if n.get("is_local"):
                    db.touch_node(n["id"])
            await _maybe_backup()
        except asyncio.CancelledError:
            break
        except Exception:  # noqa: BLE001
            await asyncio.sleep(5)


async def _keep_alive():
    """Ping the public panel port periodically so serverless/cloud hosts stay warm."""
    await asyncio.sleep(20)
    while True:
        try:
            await asyncio.sleep(300)
            async with httpx.AsyncClient(timeout=5) as client:
                await client.get(f"http://127.0.0.1:{config.PUBLIC_PORT}/health")
        except asyncio.CancelledError:
            break
        except Exception:  # noqa: BLE001
            await asyncio.sleep(5)


async def _refresh_location():
    """Refresh the edge colo and keep the local node's true region in sync.

    Cloudflare's ``colo`` remains useful for the edge-location widget and the
    panel-targeted subscription place label, but it describes the request's
    edge, not necessarily the node. Node identity/serialization therefore use
    only ``NODE_LOCATION``: a Railway replica region or this process's public
    egress-IP GeoIP result. Never use the public panel domain or edge colo as
    the node's Auto Detect result.
    """
    from .colo_map import describe_colo
    from .geo import detect_egress_location, railway_location

    _clear_node_location()
    railway_region_configured = bool(os.environ.get("RAILWAY_REPLICA_REGION", "").strip())
    while True:
        try:
            async with httpx.AsyncClient(timeout=4) as client:
                r = await client.get("https://www.cloudflare.com/cdn-cgi/trace")
                for line in r.text.splitlines():
                    if line.startswith("colo="):
                        LOCATION["colo"] = line.split("=", 1)[1]
                        break
        except Exception:  # noqa: BLE001
            pass

        # Keep the existing local-panel subscription label useful when the
        # egress IP cannot be geolocated. This fallback is marked separately
        # and is never exposed as the node's own detected location.
        edge_loc = describe_colo(LOCATION.get("colo"))
        EDGE_FALLBACK_LOCATION.clear()
        if edge_loc.get("country_code"):
            EDGE_FALLBACK_LOCATION.update(edge_loc)
            db.set_local_node_location(
                edge_loc.get("city", ""), edge_loc.get("country", ""),
                edge_loc.get("country_code", ""), edge_loc.get("flag", "🌐")
            )
        else:
            db.set_local_node_location("", "", "", "🌐")

        try:
            railway_loc = railway_location()
            if railway_region_configured:
                # Unknown Railway regions stay unknown; never substitute the edge
                # or public-domain IP location.
                local_loc = railway_loc if railway_loc.get("known") else {}
            else:
                # For generic VPS/container hosts, GeoIP the process's own
                # outbound address rather than the public domain behind a CDN.
                NODE_LOCATION.clear()
                local_loc = await asyncio.to_thread(detect_egress_location)
            if local_loc and (local_loc.get("city") or local_loc.get("country")):
                NODE_LOCATION.clear()
                NODE_LOCATION.update(local_loc)
                db.set_local_node_location(
                    local_loc.get("city", ""), local_loc.get("country", ""),
                    local_loc.get("country_code", ""), local_loc.get("flag", "🌐")
                )
            elif railway_region_configured:
                NODE_LOCATION.clear()
        except Exception:  # noqa: BLE001
            NODE_LOCATION.clear()
        await asyncio.sleep(12 * 3600)


async def _maybe_backup():
    settings = db.get_settings()
    if not settings.get("backup_enabled"):
        return
    last = float(db.get_meta("backup_last_at") or "0")
    interval = int(settings.get("backup_interval_hours", 24) or 24) * 3600
    if time.time() - last < interval:
        return
    try:
        backup_dir = os.path.join(config.DATA_DIR, "backups")
        os.makedirs(backup_dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        src = config.DB_PATH
        if not os.path.exists(src):
            return
        with open(src, "rb") as f:
            raw = f.read()
        payload = gzip.compress(raw)
        b64 = base64.b64encode(payload).decode()
        path = os.path.join(backup_dir, f"titan-{stamp}.db.gz.b64")
        with open(path, "w", encoding="utf-8") as f:
            f.write(b64)
        db.set_meta("backup_last_at", str(time.time()))
        # keep last 7 backups
        files = sorted(os.listdir(backup_dir))
        for old in files[:-7]:
            try:
                os.remove(os.path.join(backup_dir, old))
            except OSError:
                pass
        db.add_event("info", "backup", f"created {os.path.basename(path)}")
    except Exception as e:  # noqa: BLE001
        log.error("backup failed: %s", e)


async def _enrich_node_locations():
    """Fill missing country/flag for nodes that have an address, every 6h."""
    from .geo import detect_location

    await asyncio.sleep(15)
    while True:
        try:
            for n in db.list_nodes():
                if n.get("is_local"):
                    continue
                if n.get("country_code") or not (n.get("address") or "").strip():
                    continue
                loc = await asyncio.to_thread(detect_location, n["address"])
                if loc:
                    db.update_node(n["id"], {
                        "city": n.get("city") or loc["city"],
                        "country": n.get("country") or loc["country"],
                        "country_code": loc["country_code"],
                        "flag": loc["flag"],
                    })
            await asyncio.sleep(6 * 3600)
        except asyncio.CancelledError:
            break
        except Exception:  # noqa: BLE001
            await asyncio.sleep(600)


def start_background_tasks(app):
    # Run this synchronously during startup so identity endpoints cannot expose
    # a persisted Cloudflare-edge location before the refresh coroutine begins.
    _clear_node_location()
    LOCATION["colo"] = "?"
    tasks = [
        asyncio.create_task(_periodic_flush()),
        asyncio.create_task(_housekeeping()),
        asyncio.create_task(_keep_alive()),
        asyncio.create_task(_refresh_location()),
        asyncio.create_task(_enrich_node_locations()),
        asyncio.create_task(_sync_nodes_loop()),
        asyncio.create_task(_report_usage_loop()),
        asyncio.create_task(_register_with_main()),
        asyncio.create_task(_refresh_node_latencies()),
    ]
    app.state.titan_tasks = tasks
    return tasks


async def _sync_nodes_loop():
    """Main role: re-push users to remote nodes on an interval (self-healing)."""
    if config.IS_NODE:
        return
    await asyncio.sleep(10)
    while True:
        try:
            await asyncio.sleep(config.NODE_SYNC_INTERVAL)
            from . import nodes as nodesync
            await nodesync.sync_all()
        except asyncio.CancelledError:
            break
        except Exception:  # noqa: BLE001
            await asyncio.sleep(15)


async def _report_usage_loop():
    """Node role: periodically send usage deltas back to the main panel."""
    global _pending_usage
    if not config.IS_NODE:
        return
    await asyncio.sleep(20)
    while True:
        try:
            await asyncio.sleep(30)
            from . import nodes as nodesync
            # Both can appear while this process is running: a node claimed from
            # the panel learns the panel URL and the secret through bootstrap, and
            # from then on its usage has somewhere to go.
            if _pending_usage and nodesync.node_panel_url() and nodesync.node_credential():
                snapshot, _pending_usage = _pending_usage, {}
                await nodesync.report_usage(snapshot)
        except asyncio.CancelledError:
            break
        except Exception:  # noqa: BLE001
            await asyncio.sleep(10)


async def _refresh_node_latencies():
    """Main role: keep per-node latency fresh so 'auto' routing picks the
    fastest node (the /health probe also learns each node's WG public key)."""
    if config.IS_NODE:
        return
    await asyncio.sleep(12)
    while True:
        try:
            await asyncio.sleep(45)
            from . import main as m
            nodes = [
                n for n in db.list_nodes()
                if not n.get("is_local") and n.get("enabled")
                and (n.get("address") or "").strip()
            ]
            if nodes:
                await asyncio.gather(*[m._node_status(n) for n in nodes])
        except asyncio.CancelledError:
            break
        except Exception:  # noqa: BLE001
            await asyncio.sleep(15)


async def _register_with_main():
    """Node role: self-register with the main panel until it succeeds."""
    if not config.IS_NODE or not config.MAIN_URL or not config.NODE_TOKEN:
        return
    if not config.NODE_URL:
        log.warning("TITAN_NODE_URL/RAILWAY_PUBLIC_DOMAIN is empty — "
                    "generate a domain for the service so the node can register")
        return
    from . import nodes as nodesync
    await asyncio.sleep(6)
    while True:
        try:
            if await nodesync.register(config.MAIN_URL, config.NODE_TOKEN, config.NODE_URL):
                log.info("node registered with main panel (%s)", config.NODE_URL)
                return
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            break
        except Exception:  # noqa: BLE001
            await asyncio.sleep(60)
