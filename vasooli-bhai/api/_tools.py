"""Demo invoice state and the agent's local tool functions.

These are plain local Python functions (not MCP). They are stateless: each
request passes the demo state in and gets the updated state back (Vercel-safe). Every call validates its
arguments before touching state and is recorded in the event log, so the UI
only ever shows what actually executed.
"""
import copy
import datetime as dt
import os
from zoneinfo import ZoneInfo

TZ = ZoneInfo(os.environ.get("DEMO_TIMEZONE", "Asia/Kolkata"))
MAX_COMMIT_DAYS = 60


def today():
    return dt.datetime.now(TZ).date()


def fmt(d):
    return d.strftime("%A, %d %B %Y")


def _initial_invoice():
    t = today()
    return {
        "id": "INV-1042",
        "freelancer": "Aman",
        "client": "Rahul",
        "work": "Logo design",
        "amount": 8000,
        "currency": "INR",
        "due_date": (t - dt.timedelta(days=7)).isoformat(),
        "days_overdue": 7,
        "status": "Overdue",
        "previous_promise": (t - dt.timedelta(days=1)).isoformat(),
        "promised_date": None,
        "next_reminder": None,
        "reminders_paused": False,
        "contact_paused": False,
        "next_action": "Get a payment date from Rahul",
        "payment_link": None,
        "verification": None,
        "dispute": None,
        "proposal": None,
        "demo": True,
    }


def new_state():
    return {"invoice": _initial_invoice(), "events": []}


class ToolError(ValueError):
    pass


def _log(state, name, args, ok, summary):
    state["events"].append({
        "time": dt.datetime.now(TZ).strftime("%H:%M:%S"),
        "tool": name,
        "args": args,
        "ok": ok,
        "summary": summary,
    })


def _text(args, key, required=True, max_len=300):
    v = args.get(key)
    if v is None or (isinstance(v, str) and not v.strip()):
        if required:
            raise ToolError(f"'{key}' is required")
        return None
    if not isinstance(v, str):
        raise ToolError(f"'{key}' must be a string")
    return v.strip()[:max_len]


def _date(args, key, required=True):
    v = _text(args, key, required)
    if v is None:
        return None
    try:
        d = dt.date.fromisoformat(v)
    except ValueError:
        raise ToolError(f"'{key}' must be an ISO date (YYYY-MM-DD), got {v!r}")
    if d < today():
        raise ToolError(f"{d.isoformat()} is in the past")
    if d > today() + dt.timedelta(days=MAX_COMMIT_DAYS):
        raise ToolError(f"{d.isoformat()} is more than {MAX_COMMIT_DAYS} days away")
    return d


# ---- tools -----------------------------------------------------------------

def get_invoice(state, args):
    return copy.deepcopy(state["invoice"]), "Read invoice INV-1042"


def record_payment_commitment(state, args):
    if args.get("client_confirmed") is not True:
        raise ToolError("client must explicitly confirm the read-back date first")
    d = _date(args, "date")
    inv = state["invoice"]
    reminder = dt.datetime.combine(d, dt.time(10, 0))
    inv.update(
        status="Payment promised",
        promised_date=d.isoformat(),
        next_reminder=reminder.isoformat(timespec="minutes"),
        reminders_paused=False,
        next_action=f"Gentle reminder on {d.strftime('%a %d %b')}, 10:00 AM (demo, not sent)",
    )
    return {"promised_date": d.isoformat(), "next_reminder": inv["next_reminder"]}, \
        f"Commitment saved for {fmt(d)}"


def prepare_demo_payment_link(state, args):
    inv = state["invoice"]
    link = f"https://pay.example/demo/{inv['id']}?amount={inv['amount']}"
    inv["payment_link"] = link
    if inv["status"] == "Overdue":
        inv["next_action"] = "Demo payment link ready; get a payment date"
    return {"link": link, "sent": False, "demo": True}, "Demo payment link prepared (not sent)"


def flag_payment_for_verification(state, args):
    ref = _text(args, "reference", required=False, max_len=80)
    paid_on = _text(args, "paid_on", required=False, max_len=40)
    inv = state["invoice"]
    prev = inv["verification"] or {}
    inv["verification"] = {
        "reference": ref or prev.get("reference"),
        "paid_on": paid_on or prev.get("paid_on"),
        "verified": False,
    }
    inv.update(
        status="Verification needed",
        reminders_paused=True,
        next_reminder=None,
        next_action="Aman to check bank statement before any reminder",
    )
    detail = ", ".join(x for x in [ref and f"ref {ref}", paid_on and f"paid on {paid_on}"] if x)
    return {"status": inv["status"], "reminders_paused": True, "verified": False}, \
        "Flagged for verification; reminders paused" + (f" ({detail})" if detail else "")


def record_dispute(state, args):
    reason = _text(args, "reason")
    kind = _text(args, "kind", required=False, max_len=20) or "other"
    if kind not in ("amount", "work", "other"):
        raise ToolError("'kind' must be amount, work or other")
    inv = state["invoice"]
    inv.update(
        status="Disputed",
        dispute={"kind": kind, "reason": reason},
        reminders_paused=True,
        next_reminder=None,
        next_action="Aman to review the dispute",
    )
    return {"status": "Disputed", "reminders_paused": True}, f"Dispute recorded ({kind}): {reason}"


def record_payment_proposal(state, args):
    kind = _text(args, "kind", max_len=20)
    if kind not in ("new_date", "partial"):
        raise ToolError("'kind' must be new_date or partial")
    d = _date(args, "date", required=(kind == "new_date"))
    amount = args.get("amount")
    if kind == "partial":
        if not isinstance(amount, (int, float)) or isinstance(amount, bool):
            raise ToolError("'amount' (number) is required for a partial proposal")
        if not 0 < amount < state["invoice"]["amount"]:
            raise ToolError("partial amount must be between 0 and the invoice amount")
    note = _text(args, "note", required=False)
    inv = state["invoice"]
    inv.update(
        status="Proposal pending",
        proposal={"kind": kind, "amount": amount if kind == "partial" else None,
                  "date": d and d.isoformat(), "note": note, "approved": False},
        reminders_paused=True,
        next_reminder=None,
        next_action="Aman to approve or decline the proposal",
    )
    what = f"₹{amount:,.0f}" if kind == "partial" else "new date"
    return {"status": inv["status"], "approved": False}, \
        f"Proposal recorded: {what}" + (f" by {fmt(d)}" if d else "") + " — awaiting Aman"


def pause_contact(state, args):
    reason = _text(args, "reason", required=False) or "Client asked to stop"
    inv = state["invoice"]
    inv.update(
        status="Contact paused",
        contact_paused=True,
        reminders_paused=True,
        next_reminder=None,
        next_action="No further contact; Aman to decide next step",
    )
    return {"status": "Contact paused"}, f"Contact paused: {reason}"


TOOLS = {
    "get_invoice": get_invoice,
    "record_payment_commitment": record_payment_commitment,
    "prepare_demo_payment_link": prepare_demo_payment_link,
    "flag_payment_for_verification": flag_payment_for_verification,
    "record_dispute": record_dispute,
    "record_payment_proposal": record_payment_proposal,
    "pause_contact": pause_contact,
}


def call(state, name, args):
    """Run a tool against `state`. Returns {"ok", "result"|"error"}; always logged."""
    args = args if isinstance(args, dict) else {}
    fn = TOOLS.get(name)
    if fn is None:
        _log(state, name, args, False, "Unknown tool")
        return {"ok": False, "error": f"unknown tool {name}"}
    if state["invoice"]["contact_paused"] and name != "get_invoice":
        _log(state, name, args, False, "Rejected: contact is paused")
        return {"ok": False, "error": "contact is paused; no further actions"}
    try:
        result, summary = fn(state, args)
    except ToolError as e:
        _log(state, name, args, False, f"Rejected: {e}")
        return {"ok": False, "error": str(e)}
    _log(state, name, args, True, summary)
    return {"ok": True, "result": result}


SCHEMAS = [
    {"type": "function", "function": {
        "name": "get_invoice", "description": "Read the current invoice state.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "record_payment_commitment",
        "description": "Save a payment date ONLY after you read the exact date back and the client said yes.",
        "parameters": {"type": "object", "properties": {
            "date": {"type": "string", "description": "YYYY-MM-DD"},
            "client_confirmed": {"type": "boolean"}},
            "required": ["date", "client_confirmed"]}}},
    {"type": "function", "function": {
        "name": "prepare_demo_payment_link",
        "description": "Prepare a DEMO payment link shown on screen. It is not sent anywhere.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "flag_payment_for_verification",
        "description": "Client says they already paid. Pauses reminders; never marks paid.",
        "parameters": {"type": "object", "properties": {
            "reference": {"type": "string"}, "paid_on": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "record_dispute",
        "description": "Client disputes the work or amount. Pauses reminders for Aman's review.",
        "parameters": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": ["amount", "work", "other"]},
            "reason": {"type": "string"}}, "required": ["kind", "reason"]}}},
    {"type": "function", "function": {
        "name": "record_payment_proposal",
        "description": "Record a new-date or partial-payment proposal for Aman's approval. Never accept it yourself.",
        "parameters": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": ["new_date", "partial"]},
            "date": {"type": "string", "description": "YYYY-MM-DD"},
            "amount": {"type": "number"}, "note": {"type": "string"}},
            "required": ["kind"]}}},
    {"type": "function", "function": {
        "name": "pause_contact", "description": "Client asked to stop being contacted.",
        "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}}}},
]
