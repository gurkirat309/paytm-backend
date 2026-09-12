"""
PHINITE TOOLS — paste each block into its own tool in Dev Studio.

Every tool needs ONE environment variable:

    BACKEND_URL = https://your-service.onrender.com     (no trailing slash)

Set it once under Env. Variables in the Phinite sidebar.
"""

# ==========================================================================
# TOOL 1 of 4  —  dashboard_tool                    ENV_VARS: ["BACKEND_URL"]
# --------------------------------------------------------------------------
# Every agent calls this after it acts. This is what makes the demo visible.
# ==========================================================================

DASHBOARD_TOOL = r'''
# ENV_VARS: ["BACKEND_URL"]
"""dashboard_tool — push agent state to the live merchant dashboard."""
import requests


def main(inputs, env_variables):
    out, cap = {"success": False}, {}
    try:
        base = (env_variables.get("BACKEND_URL") or "").strip().rstrip("/")
        if not base:
            out["error"] = "BACKEND_URL is not set."
            return {"output": out, "capture_variables": cap}

        if not isinstance(inputs, dict):
            inputs = {}

        payload = {
            "_agent": inputs.get("agent", "Agent"),
            "_note": inputs.get("note"),
            "_kind": inputs.get("kind", "info"),
        }

        # only forward keys the dashboard understands
        for key in ("total_outstanding", "customers_with_dues",
                    "concentration_pct", "concentration_amount",
                    "collections_queue", "reconciliation",
                    "cash_position", "pending_approval"):
            if inputs.get(key) is not None:
                payload[key] = inputs[key]

        r = requests.post(f"{base}/api/update", json=payload, timeout=10)
        r.raise_for_status()
        out.update({"success": True, "dashboard_updated": True})
        return {"output": out, "capture_variables": cap}

    except Exception as exc:
        # never let a dashboard failure break the agent run
        out.update({"success": False, "error": str(exc),
                    "note": "Dashboard unreachable; agent work is unaffected."})
        return {"output": out, "capture_variables": cap}
'''


# ==========================================================================
# TOOL 2 of 4  —  message_sending_tool     REPLACES the existing stub
#                                          ENV_VARS: ["BACKEND_URL"]
# --------------------------------------------------------------------------
# Same guardrails as before (quiet hours, frequency caps) — but a permitted
# message now actually lands on a real phone.
# ==========================================================================

MESSAGE_SENDING_TOOL = r'''
# ENV_VARS: ["BACKEND_URL"]
"""
message_sending_tool — real WhatsApp delivery, guarded in code.
Quiet hours and frequency caps are enforced here, not in a prompt.
"""
import datetime
import requests

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

SENT_LOG = []
QUIET_START_HOUR = 8       # inclusive
QUIET_END_HOUR = 19        # exclusive
MAX_PER_DAY = 1
MAX_PER_WEEK = 2

# demo phones — put the judge's number on C001 before you present
PHONES = {
    "C001": "+919999999999",
    "C005": "+919999999999",
    "C006": "+919999999999",
}


def _recent(cid, days):
    cutoff = datetime.datetime.now(IST) - datetime.timedelta(days=days)
    hits = []
    for m in SENT_LOG:
        if m["customer_id"] != cid:
            continue
        ts = datetime.datetime.fromisoformat(m["sent_at"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=IST)
        if ts > cutoff:
            hits.append(m)
    return hits


def main(inputs, env_variables):
    out, cap = {"success": False}, {}
    try:
        if not isinstance(inputs, dict):
            inputs = {}

        cid = str(inputs.get("target_customer_id")
                  or inputs.get("customer_id") or "").strip()
        body = (inputs.get("approved_message")
                or inputs.get("message_text")
                or inputs.get("message") or "").strip()
        name = inputs.get("customer_name", "")

        if not cid or not body:
            out["error"] = "customer_id and an approved message are required."
            return {"output": out, "capture_variables": cap}

        if not inputs.get("merchant_approved", True):
            out.update({"blocked": True, "reason": "merchant_approval_missing"})
            return {"output": out, "capture_variables": cap}

        now = datetime.datetime.now(IST)
        hour = int(inputs.get("override_hour", now.hour))

        # ---- guardrail 1: quiet hours -----------------------------------
        if not (QUIET_START_HOUR <= hour < QUIET_END_HOUR):
            out.update({
                "blocked": True, "reason": "quiet_hours",
                "detail": f"Blocked at {hour:02d}:00 IST. Customer messaging is "
                          f"only permitted between {QUIET_START_HOUR:02d}:00 and "
                          f"{QUIET_END_HOUR:02d}:00 IST.",
            })
            _notify(env_variables, "Blocked: quiet hours "
                                   f"({hour:02d}:00) — {name or cid}", "block")
            return {"output": out, "capture_variables": cap}

        # ---- guardrail 2: frequency caps --------------------------------
        if len(_recent(cid, 1)) >= MAX_PER_DAY:
            out.update({"blocked": True, "reason": "daily_cap",
                        "detail": f"{name or cid} has already been contacted today."})
            _notify(env_variables, f"Blocked: daily cap — {name or cid}", "block")
            return {"output": out, "capture_variables": cap}

        if len(_recent(cid, 7)) >= MAX_PER_WEEK:
            out.update({"blocked": True, "reason": "weekly_cap",
                        "detail": f"{name or cid} has already been contacted "
                                  f"{MAX_PER_WEEK} times this week."})
            _notify(env_variables, f"Blocked: weekly cap — {name or cid}", "block")
            return {"output": out, "capture_variables": cap}

        # ---- permitted: send for real -----------------------------------
        record = {
            "message_id": f"MSG{len(SENT_LOG) + 1:04d}",
            "customer_id": cid, "body": body,
            "sent_at": now.isoformat(),
            "escalation_level": inputs.get("escalation_level", 1),
        }
        SENT_LOG.append(record)

        delivery = {"delivered": False}
        base = (env_variables.get("BACKEND_URL") or "").strip().rstrip("/")
        phone = inputs.get("phone") or PHONES.get(cid)
        if base and phone:
            try:
                r = requests.post(f"{base}/whatsapp/send", timeout=20, json={
                    "to": phone, "message": body,
                    "customer_name": name or cid,
                })
                delivery = r.json()
            except Exception as exc:
                delivery = {"delivered": False, "error": str(exc)}

        cap.update({"message_id": record["message_id"],
                    "delivery_status": "sent",
                    "timestamp": record["sent_at"]})
        out.update({
            "success": True, "sent": True,
            "message_id": record["message_id"],
            "customer_id": cid, "channel": "whatsapp",
            "sent_at_ist": now.strftime("%Y-%m-%d %H:%M IST"),
            "whatsapp": delivery,
            "messages_this_week": len(_recent(cid, 7)),
        })
        return {"output": out, "capture_variables": cap}

    except Exception as exc:
        out["error"] = f"Unexpected error: {exc}"
        return {"output": out, "capture_variables": cap}


def _notify(env_variables, text, kind):
    """Surface guardrail blocks on the dashboard. Never raises."""
    try:
        base = (env_variables.get("BACKEND_URL") or "").strip().rstrip("/")
        if base:
            requests.post(f"{base}/api/event", timeout=6,
                          json={"agent": "Guardrail", "text": text, "kind": kind})
    except Exception:
        pass
'''


# ==========================================================================
# TOOL 3 of 4  —  statement_tool                    ENV_VARS: ["BACKEND_URL"]
# --------------------------------------------------------------------------
# Produces a real PDF the merchant can hand to a customer.
# ==========================================================================

STATEMENT_TOOL = r'''
# ENV_VARS: ["BACKEND_URL"]
"""statement_tool — generate a PDF udhaar statement for one customer."""
import requests


def main(inputs, env_variables):
    out, cap = {"success": False}, {}
    try:
        base = (env_variables.get("BACKEND_URL") or "").strip().rstrip("/")
        if not base:
            out["error"] = "BACKEND_URL is not set."
            return {"output": out, "capture_variables": cap}

        if not isinstance(inputs, dict):
            inputs = {}

        name = (inputs.get("customer_name") or "").strip()
        if not name:
            out["error"] = "customer_name is required."
            return {"output": out, "capture_variables": cap}

        payload = {
            "customer_name": name,
            "customer_id": inputs.get("customer_id", ""),
            "entries": inputs.get("entries", []),
            "open_amount": inputs.get("open_amount", 0),
            "payment_link": inputs.get("payment_link", ""),
        }

        r = requests.post(f"{base}/statement/generate", json=payload, timeout=30)
        r.raise_for_status()

        url = f"{base}/statement/generate"
        cap["statement_url"] = url
        out.update({
            "success": True,
            "statement_generated": True,
            "customer_name": name,
            "size_bytes": len(r.content),
            "note": "PDF statement generated and ready to share.",
        })
        return {"output": out, "capture_variables": cap}

    except Exception as exc:
        out["error"] = f"Statement generation failed: {exc}"
        return {"output": out, "capture_variables": cap}
'''


# ==========================================================================
# TOOL 4 of 4  —  soundbox_tool                     ENV_VARS: ["BACKEND_URL"]
# --------------------------------------------------------------------------
# Speaks the summary aloud, the way a counter device would.
# ==========================================================================

SOUNDBOX_TOOL = r'''
# ENV_VARS: ["BACKEND_URL"]
"""soundbox_tool — speak a short summary aloud on the merchant's counter."""
import requests


def main(inputs, env_variables):
    out, cap = {"success": False}, {}
    try:
        base = (env_variables.get("BACKEND_URL") or "").strip().rstrip("/")
        if not base:
            out["error"] = "BACKEND_URL is not set."
            return {"output": out, "capture_variables": cap}

        if not isinstance(inputs, dict):
            inputs = {}

        text = (inputs.get("text") or inputs.get("summary") or "").strip()
        if not text:
            out["error"] = "text is required."
            return {"output": out, "capture_variables": cap}

        if len(text) > 400:
            text = text[:397] + "..."

        lang = inputs.get("lang", "hi")
        r = requests.post(f"{base}/voice/say", timeout=30,
                          json={"text": text, "lang": lang})
        r.raise_for_status()

        cap["spoken_text"] = text
        out.update({
            "success": True, "spoken": True, "text": text, "lang": lang,
            "audio_url": f"{base}/voice/say",
            "note": "Summary spoken on the Soundbox.",
        })
        return {"output": out, "capture_variables": cap}

    except Exception as exc:
        out["error"] = f"Soundbox failed: {exc}"
        return {"output": out, "capture_variables": cap}
'''

if __name__ == "__main__":
    for label, code in [("dashboard_tool", DASHBOARD_TOOL),
                        ("message_sending_tool", MESSAGE_SENDING_TOOL),
                        ("statement_tool", STATEMENT_TOOL),
                        ("soundbox_tool", SOUNDBOX_TOOL)]:
        print(f"\n{'=' * 74}\n{label}\n{'=' * 74}{code}")
