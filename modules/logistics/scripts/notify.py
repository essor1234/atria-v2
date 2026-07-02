#!/usr/bin/env python
"""Post-booking Zalo notification for the logistics module.

After a booking is confirmed, notify the business OWNER on Zalo (a heads-up sent
FROM the business Official Account via a free OA "consultation"/CS message).

Self-contained (stdlib only). Prints JSON to stdout, like the other module
scripts. Safe by default: if Zalo credentials or the owner's user id are not
configured, `send` runs in DRY-RUN and posts nothing.

Subcommands:
  send           compose + send (or dry-run) the owner notification for a booking
  exchange-code  one-time OAuth: turn an authorization code into access/refresh tokens
  refresh-token  refresh the access token from the stored refresh token
  recent-chats   list the OA's recent conversations (to find the owner's user_id)

Config (from environment; the backend loads .env, so set them there):
  ZALO_APP_ID            developer app id
  ZALO_APP_SECRET        developer app secret
  ZALO_OWNER_USER_ID     the owner's user id as seen by the OA (recipient)
  ZALO_OA_ACCESS_TOKEN   optional seed access token (token store takes precedence)

Tokens rotate, so they live in a token store file (NOT .env):
  modules/logistics/data/.zalo_token.json  {access_token, refresh_token, expires_at}

NOTE: Zalo has versioned these endpoints; verify the v3.0 CS path/headers and the
v4 OAuth endpoint against the live API explorer at developers.zalo.me before the
first live send. CS messages only deliver inside Zalo's interaction window after
the recipient last messaged the OA.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
BOOKINGS_CSV = DATA_DIR / "bookings.csv"
TOKEN_STORE = DATA_DIR / ".zalo_token.json"

# Zalo endpoints (verify against developers.zalo.me before the live test).
OAUTH_URL = "https://oauth.zaloapp.com/v4/oa/access_token"
CS_MESSAGE_URL = "https://openapi.zalo.me/v3.0/oa/message/cs"
RECENT_CHAT_URL = "https://openapi.zalo.me/v3.0/oa/listrecentchat"

HTTP_TIMEOUT = 20


# --------------------------------------------------------------- booking read

def _load_booking(booking_id: str) -> dict | None:
    """Return one booking grouped across its truck rows, or None if not found."""
    if not BOOKINGS_CSV.exists():
        return None
    group: dict | None = None
    with BOOKINGS_CSV.open("r", newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("booking_id") != booking_id:
                continue
            if group is None:
                group = {
                    "booking_id": r.get("booking_id", ""),
                    "customer": r.get("customer", ""),
                    "status": r.get("status", ""),
                    "destination_zone": r.get("destination_zone", ""),
                    "requested_weight_t": r.get("requested_weight_t", ""),
                    "notes": r.get("notes", ""),
                    "trucks": [],
                }
            if r.get("vehicle_number"):
                group["trucks"].append({
                    "vehicle_number": r.get("vehicle_number", ""),
                    "driver_name": r.get("driver_name", ""),
                    "delivery_time": r.get("delivery_time", ""),
                })
    return group


def _compose_message(g: dict) -> str:
    """Deterministic Vietnamese owner summary for a confirmed booking."""
    lines = [
        f"Booking {g['booking_id']} ({g['status']}) - KH {g['customer']}, "
        f"tuyen {g['destination_zone']}, {g['requested_weight_t']}T."
    ]
    if g["trucks"]:
        for t in g["trucks"]:
            plate = t["vehicle_number"] or "?"
            driver = t["driver_name"] or "?"
            when = t["delivery_time"] or "?"
            lines.append(f"- Xe {plate} / {driver} @ {when}")
    else:
        lines.append("- (chua gan xe)")
    return "\n".join(lines)


# ----------------------------------------------------------------- token store

def _read_store() -> dict:
    if TOKEN_STORE.exists():
        try:
            return json.loads(TOKEN_STORE.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {}
    return {}


def _write_store(data: dict) -> None:
    TOKEN_STORE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _redact(token: str | None) -> str:
    if not token:
        return ""
    return token[:6] + "..." + token[-4:] if len(token) > 12 else "***"


# ------------------------------------------------------------------- http glue

def _post_form(url: str, *, headers: dict, params: dict) -> tuple[int, dict]:
    body = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    return _send(req)


def _post_json(url: str, *, headers: dict, payload: dict) -> tuple[int, dict]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    req.add_header("Content-Type", "application/json")
    return _send(req)


def _get(url: str, *, headers: dict) -> tuple[int, dict]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    return _send(req)


def _send(req: urllib.request.Request) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, _parse(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace") if exc.fp else ""
        return exc.code, _parse(raw)
    except urllib.error.URLError as exc:
        return 0, {"error": f"network error: {exc.reason}"}


def _parse(raw: str) -> dict:
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        return {"_raw": raw}


# ------------------------------------------------------------------- token mgmt

def _refresh_access_token() -> tuple[str | None, str]:
    """Refresh using the stored refresh token. Returns (access_token, reason)."""
    store = _read_store()
    refresh = store.get("refresh_token")
    app_id = os.getenv("ZALO_APP_ID")
    app_secret = os.getenv("ZALO_APP_SECRET")
    if not (refresh and app_id and app_secret):
        return None, "missing refresh_token / ZALO_APP_ID / ZALO_APP_SECRET"
    # Zalo v4: secret_key goes in the header; body carries grant + refresh token.
    status, data = _post_form(
        OAUTH_URL,
        headers={"secret_key": app_secret},
        params={"app_id": app_id, "grant_type": "refresh_token", "refresh_token": refresh},
    )
    access = data.get("access_token")
    if not access:
        return None, f"refresh failed (http {status}): {json.dumps(data, ensure_ascii=False)}"
    _persist_tokens(data)
    return access, "refreshed"


def _persist_tokens(data: dict) -> None:
    store = _read_store()
    store["access_token"] = data.get("access_token", store.get("access_token"))
    # Zalo rotates the refresh token on every refresh (single-use) — keep the new one.
    if data.get("refresh_token"):
        store["refresh_token"] = data["refresh_token"]
    try:
        ttl = int(data.get("expires_in", "0"))
    except (TypeError, ValueError):
        ttl = 0
    store["expires_at"] = int(time.time()) + ttl - 60 if ttl else 0
    _write_store(store)


def _get_access_token() -> tuple[str | None, str]:
    """Return a usable access token (refreshing if needed), plus a reason string."""
    store = _read_store()
    access = store.get("access_token")
    expires_at = store.get("expires_at") or 0
    if access and (expires_at == 0 or expires_at > time.time()):
        return access, "store"
    if store.get("refresh_token"):
        return _refresh_access_token()
    env_token = os.getenv("ZALO_OA_ACCESS_TOKEN")
    if env_token:
        return env_token, "env seed"
    return None, "no token (run exchange-code, or set ZALO_OA_ACCESS_TOKEN)"


# ---------------------------------------------------------------- subcommands

def cmd_send(args: argparse.Namespace) -> int:
    g = _load_booking(args.booking)
    if g is None:
        print(json.dumps({"error": f"booking not found: {args.booking}"}, ensure_ascii=False))
        return 1

    message = args.text if args.text else _compose_message(g)
    recipient = os.getenv("ZALO_OWNER_USER_ID")

    # Decide dry-run: explicit flag, or missing recipient/token.
    token, token_reason = (None, "dry-run flag") if args.dry_run else _get_access_token()
    dry = args.dry_run or not recipient or not token
    if dry:
        reason = (
            "dry-run flag" if args.dry_run
            else "ZALO_OWNER_USER_ID not set" if not recipient
            else token_reason
        )
        print(json.dumps({
            "mode": "dry-run",
            "reason": reason,
            "booking_id": g["booking_id"],
            "recipient": recipient or "(unset)",
            "message": message,
        }, ensure_ascii=False))
        return 0

    status, data = _post_json(
        CS_MESSAGE_URL,
        headers={"access_token": token},
        payload={"recipient": {"user_id": recipient}, "message": {"text": message}},
    )
    ok = status == 200 and data.get("error", 0) in (0, None)
    print(json.dumps({
        "mode": "live",
        "ok": ok,
        "http_status": status,
        "booking_id": g["booking_id"],
        "recipient": recipient,
        "message": message,
        "zalo_response": data,
    }, ensure_ascii=False))
    return 0 if ok else 1


def cmd_exchange_code(args: argparse.Namespace) -> int:
    app_id = os.getenv("ZALO_APP_ID")
    app_secret = os.getenv("ZALO_APP_SECRET")
    if not (app_id and app_secret):
        print(json.dumps({"error": "set ZALO_APP_ID and ZALO_APP_SECRET first"}, ensure_ascii=False))
        return 1
    status, data = _post_form(
        OAUTH_URL,
        headers={"secret_key": app_secret},
        params={"app_id": app_id, "grant_type": "authorization_code", "code": args.code},
    )
    if not data.get("access_token"):
        print(json.dumps({"ok": False, "http_status": status, "zalo_response": data},
                         ensure_ascii=False))
        return 1
    _persist_tokens(data)
    store = _read_store()
    print(json.dumps({
        "ok": True,
        "stored": str(TOKEN_STORE),
        "access_token": _redact(store.get("access_token")),
        "refresh_token": _redact(store.get("refresh_token")),
        "expires_at": store.get("expires_at"),
    }, ensure_ascii=False))
    return 0


def cmd_refresh_token(_args: argparse.Namespace) -> int:
    access, reason = _refresh_access_token()
    store = _read_store()
    print(json.dumps({
        "ok": bool(access),
        "reason": reason,
        "access_token": _redact(store.get("access_token")),
        "refresh_token": _redact(store.get("refresh_token")),
        "expires_at": store.get("expires_at"),
    }, ensure_ascii=False))
    return 0 if access else 1


def cmd_recent_chats(args: argparse.Namespace) -> int:
    token, reason = _get_access_token()
    if not token:
        print(json.dumps({"error": reason}, ensure_ascii=False))
        return 1
    query = urllib.parse.urlencode({"data": json.dumps({"offset": 0, "count": args.count})})
    status, data = _get(f"{RECENT_CHAT_URL}?{query}", headers={"access_token": token})
    print(json.dumps({"http_status": status, "zalo_response": data}, ensure_ascii=False))
    return 0 if status == 200 else 1


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Zalo owner notification for logistics bookings.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_send = sub.add_parser("send", help="notify the owner about a booking (dry-run by default)")
    p_send.add_argument("--booking", required=True, help="booking_id, e.g. BK-0001")
    p_send.add_argument("--text", help="override the default composed message")
    p_send.add_argument("--dry-run", action="store_true", help="compose only; send nothing")
    p_send.set_defaults(fn=cmd_send)

    p_ex = sub.add_parser("exchange-code", help="one-time: authorization code -> tokens")
    p_ex.add_argument("--code", required=True, help="OAuth authorization code from the app dashboard")
    p_ex.set_defaults(fn=cmd_exchange_code)

    p_rt = sub.add_parser("refresh-token", help="refresh + persist the access token")
    p_rt.set_defaults(fn=cmd_refresh_token)

    p_rc = sub.add_parser("recent-chats", help="list recent OA conversations (find owner user_id)")
    p_rc.add_argument("--count", type=int, default=10)
    p_rc.set_defaults(fn=cmd_recent_chats)

    args = parser.parse_args(argv[1:])
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
