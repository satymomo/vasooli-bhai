"""Conversation logic: a Sarvam LLM agent (live) and a scripted agent (text demo).

Both agents change invoice state only through tools.call(), so the UI reflects
real tool results rather than anything claimed in the reply text.
"""
import datetime as dt
import json
import re

import _tools as tools

OPENING = ("Hi Rahul, main Aman ka AI payment assistant, Vasooli Bhai. Logo design ka "
           "₹8,000 invoice pending hai. Ek minute baat kar sakte hain?")

WEEKDAYS = {
    0: ["monday", "mon", "somvar", "somwar", "सोमवार"],
    1: ["tuesday", "tue", "mangalvar", "mangalwar", "मंगलवार"],
    2: ["wednesday", "wed", "budhvar", "budhwar", "बुधवार"],
    3: ["thursday", "thu", "guruvar", "guruwar", "veervar", "गुरुवार"],
    4: ["friday", "fri", "shukravar", "shukrawar", "शुक्रवार", "फ्राइडे"],
    5: ["saturday", "sat", "shanivar", "shaniwar", "शनिवार"],
    6: ["sunday", "sun", "ravivar", "raviwar", "itvaar", "रविवार", "संडे"],
}
MONTHS = {m.lower(): i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def short(d):
    return d.strftime("%A, %d %B")


def parse_date(text):
    """Resolve a spoken date to (date, ambiguous_note) relative to the local date."""
    t = text.lower()
    today = tools.today()
    words = set(re.findall(r"[\wऀ-ॿ]+", t))
    if words & {"parso", "parson", "परसों"} or "day after tomorrow" in t:
        return today + dt.timedelta(days=2), None
    if words & {"kal", "tomorrow", "कल"}:
        return today + dt.timedelta(days=1), None
    if words & {"aaj", "today", "आज"} and not words & {"nahi", "not"}:
        return today, None
    nxt = bool(words & {"next", "agle", "agla", "अगले"})
    for wd, names in WEEKDAYS.items():
        if words & set(names):
            delta = (wd - today.weekday()) % 7 or 7
            if nxt and delta < 7:
                delta += 7
            return today + dt.timedelta(days=delta), None
    m = re.search(r"\b(\d{1,2})\s*(?:st|nd|rd|th)?\s*(?:tarikh|tareekh|तारीख)?\s*([a-z]{3})?", t)
    if m and (m.group(2) in MONTHS or "tarikh" in t or "tareekh" in t or "तारीख" in t):
        day, month = int(m.group(1)), MONTHS.get(m.group(2) or "")
        try:
            if month:  # "30 oct": this year, else next year
                d = dt.date(today.year, month, day)
                return (d if d >= today else d.replace(year=today.year + 1)), None
            d = dt.date(today.year, today.month, day)  # "30 tarikh": this month, else next
            if d < today:
                y, mo = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
                d = dt.date(y, mo, day)
            return d, None
        except ValueError:
            return None, None
    return None, None


def has(text, *keys):
    t = text.lower()
    return any(k in t for k in keys)


YES = ("haan", "han ", "haa", "yes", "yeah", "yep", "theek", "thik", "sahi", "confirm", "ok",
       "okay", "bilkul", "pakka", "done", "हाँ", "हां", "ठीक", "सही", "जी")
NO = ("nahi", "nahin", "no ", "nope", "galat", "नहीं")


class ScriptedAgent:
    """Deterministic rules used when Sarvam credentials are missing."""

    def __init__(self, st):
        self.st = st
        self.mem = st.setdefault("agent", {"pending": None, "joked": False})

    @property
    def pending(self):   # (kind, data); dates are stored as ISO strings in state
        p = self.mem["pending"]
        if not p:
            return None
        kind, data = p
        return kind, dt.date.fromisoformat(data) if kind == "confirm_date" else data

    @pending.setter
    def pending(self, value):
        if value and isinstance(value[1], dt.date):
            value = (value[0], value[1].isoformat())
        self.mem["pending"] = list(value) if value else None

    @property
    def joked(self):
        return self.mem["joked"]

    @joked.setter
    def joked(self, value):
        self.mem["joked"] = value

    def opening(self):
        tools.call(self.st, "get_invoice", {})
        return OPENING

    def reply(self, text):
        t = " " + text.lower().strip() + " "
        if self.st["invoice"]["contact_paused"]:
            return "Contact paused hai. Aman khud aapse baat karenge agar zaroorat hui. Dhanyavaad."

        # 1. Stop always wins.
        if has(t, "stop", "mat karo", "band karo", "contact mat", "call mat", "don't contact",
               "dont contact", "don't call", "leave me", "बंद", "मत करो"):
            self.pending = None
            tools.call(self.st, "pause_contact", {"reason": text.strip()})
            return "Bilkul, samajh gaya. Main aage contact nahi karunga. Aman ko bata diya jayega. Dhanyavaad, Rahul."

        kind, data = self.pending or (None, None)

        # 2. Answers to a question we asked.
        if kind == "confirm_date":
            new, _ = parse_date(t)
            if new and new != data:
                self.pending = ("confirm_date", new)
                return f"Theek hai, toh {short(new)}. Ye date confirm hai?"
            if has(t, *YES) and not has(t, "nahi", "नहीं"):
                r = tools.call(self.st, "record_payment_commitment",
                               {"date": data.isoformat(), "client_confirmed": True})
                self.pending = None
                if not r["ok"]:
                    return f"Ye date save nahi ho payi: {r['error']}. Koi aur date bata denge?"
                return (f"Done, {short(data)} note kar liya. Us din subah ek gentle reminder set hai. "
                        "Thank you, Rahul!")
            if has(t, *NO):
                self.pending = ("ask_date", None)
                return "Koi baat nahi. Phir kaunsi date pakki rahegi?"
            return f"Bas confirm kar doon: {short(data)} ko payment hoga, haan ya na?"

        if kind == "paid_ref":
            self.pending = None
            r = tools.call(self.st, "flag_payment_for_verification", {"reference": text.strip()[:80]})
            if not r["ok"]:
                return "Detail save nahi ho payi. Aman se aap seedha share kar dijiye."
            return ("Shukriya. Maine detail note kar li hai. Aman bank mein check karke confirm karenge; "
                    "tab tak koi reminder nahi aayega.")

        if kind == "dispute_detail":
            self.pending = None
            tools.call(self.st, "record_dispute", {"kind": data, "reason": text.strip()})
            return "Samajh gaya, maine aapki baat Aman ke review ke liye note kar li hai. Woh aapse khud baat karenge."

        if kind == "proposal":
            d, _ = parse_date(t)
            amt = re.search(r"(\d[\d,]{2,})", t)
            if amt:
                r = tools.call(self.st, "record_payment_proposal", {
                    "kind": "partial", "amount": int(amt.group(1).replace(",", "")),
                    "date": d.isoformat() if d else None, "note": text.strip()})
            elif d:
                r = tools.call(self.st, "record_payment_proposal", {
                    "kind": "new_date", "date": d.isoformat(), "note": text.strip()})
            else:
                return "Koi date ya amount bata dijiye, main Aman ke paas proposal bhej dunga approval ke liye."
            self.pending = None
            if not r["ok"]:
                return f"Ye proposal save nahi ho paya: {r['error']}. Thoda alag bata denge?"
            return ("Note kar liya. Ye abhi sirf proposal hai; Aman approve karenge toh aapko confirm ho jayega. "
                    "Thanks for being upfront.")

        if kind == "link_offer":
            self.pending = None
            if has(t, *YES):
                tools.call(self.st, "prepare_demo_payment_link", {})
                self.pending = ("ask_date", None)
                return "Link screen pe ready hai. Aur payment kab tak ho jayega, koi date bata denge?"

        # 3. Fresh intents.
        if has(t, "already paid", "paid already", "pay kar diya", "pay kar chuka", "bhej diya",
               "transfer kar diya", "de diya", "kar diya hai", "payment ho gaya", "paid it", " paid "):
            tools.call(self.st, "flag_payment_for_verification", {})
            self.pending = ("paid_ref", None)
            return "Achha, thank you! Verify karne ke liye reference number ya payment date bata denge?"

        if has(t, "wrong", "galat", "zyada", "jyada", "too much", "dispute", "not happy", "kharab",
               "pasand nahi", "incomplete", "pura nahi", "not done", "not what"):
            k = "amount" if has(t, "amount", "price", "₹", "rupay", "paisa", "paise", "zyada",
                                "jyada", "too much", "8000", "8,000") else "work"
            tools.call(self.st, "record_dispute", {"kind": k, "reason": text.strip()})
            self.pending = ("dispute_detail", k)
            if k == "amount":
                return "Samjha. Aapke hisaab se kya galat hai, aur kitna hona chahiye tha?"
            return "Samjha. Kaam ka kaunsa part theek nahi laga?"

        if has(t, "can't pay", "cant pay", "cannot pay", "nahi kar sakta", "nahi kar paunga",
               "paise nahi", "paisa nahi", "tight", "mushkil", "problem hai", "partial", "half", "aadha"):
            self.pending = ("proposal", None)
            return ("Samajh sakta hoon, koi pressure nahi. Kya aap koi aur date propose karna chahenge, "
                    "ya abhi partial payment?")

        if has(t, "bhool", "forgot", "yaad nahi", "slipped", "भूल"):
            self.pending = ("link_offer", None)
            return "Arre, hota hai! Ek demo payment link taiyaar kar doon, taaki ek click mein ho jaaye?"

        d, _ = parse_date(t)
        if d:
            self.pending = ("confirm_date", d)
            return f"Theek hai. Kal ki commitment miss ho gayi thi, isliye pakka kar loon: {short(d)}. Confirm?"

        if has(t, *YES):
            self.pending = ("ask_date", None)
            if not self.joked:
                self.joked = True
                return ("Thank you! Main follow-up sambhaal leta hoon, taaki Aman design pe focus kar sake. "
                        "Payment kab tak ho jayega?")
            return "Payment kab tak ho jayega?"

        if has(t, "abhi nahi", "not now", "later", "baad mein", "busy"):
            self.pending = ("ask_date", None)
            return "Kal ki commitment miss ho gayi. Is baar kaunsi date realistic rahegi?"

        return "Sorry, theek se samjha nahi. Payment ke liye kaunsi date aapke liye realistic hai?"


def system_prompt(st):
    today = tools.today()
    days = "\n".join(
        f"- {(today + dt.timedelta(days=i)).strftime('%A %d %B %Y')} = "
        f"{(today + dt.timedelta(days=i)).isoformat()}" + (" (today)" if i == 0 else " (kal)" if i == 1 else "")
        for i in range(15))
    inv = st["invoice"]
    return f"""You are Vasooli Bhai, Aman's AI payment assistant, on a voice call with client Rahul.
Invoice {inv['id']}: {inv['work']}, ₹8,000, due {inv['due_date']}, 7 days overdue.
Rahul promised payment yesterday ({inv['previous_promise']}) and missed it.

Local dates (use these, never compute dates yourself):
{days}

Style: warm, witty, natural Hinglish (Roman script). Max 2 short sentences. Exactly one question per turn.
Increasingly firm when commitments are missed: firmness = asking for a clear next step.
Never threaten, insult, shame, or pressure someone describing hardship. Don't repeat jokes.
Never claim a message was sent, a payment verified, or a proposal accepted.

Rules (state only changes via tools):
- Forgot: offer a demo payment link; call prepare_demo_payment_link if they agree.
- Date mentioned: read back the full date (weekday + date) and ask to confirm. Only after a clear yes,
  call record_payment_commitment with client_confirmed=true. Then mention the reminder on that date.
- Already paid: call flag_payment_for_verification immediately, ask for reference or payment date,
  then call it again with what they give. Never say it is paid.
- Dispute about work/amount: call record_dispute, ask one short clarifying question. Never negotiate
  or change the amount; Aman will review.
- Cannot pay: ask if they want to propose another date or a partial payment, then call
  record_payment_proposal. Say Aman must approve; never accept it yourself.
- Stop contacting: call pause_contact and end politely in one sentence.
If a tool returns an error, tell them briefly and ask again. Reply in plain spoken text, no markdown."""


class LLMAgent:
    """sarvam-105b-conversations with tool calling."""

    MODEL = "sarvam-105b-conversations"

    def __init__(self, client, st):
        self.client = client
        self.st = st
        self.messages = st.setdefault("messages", [])

    def opening(self):
        tools.call(self.st, "get_invoice", {})
        self.messages[:] = [{"role": "assistant", "content": OPENING}]
        return OPENING

    def reply(self, text):
        self.messages.append({"role": "user", "content": text})
        for _ in range(5):
            resp = self.client.chat.completions(
                model=self.MODEL,
                messages=[{"role": "system", "content": system_prompt(self.st)}] + self.messages,
                tools=tools.SCHEMAS,
                temperature=0.4,
            )
            msg = resp.choices[0].message
            calls = getattr(msg, "tool_calls", None) or []
            if not calls:
                content = re.sub(r"<think>.*?</think>", "", msg.content or "", flags=re.S).strip()
                self.messages.append({"role": "assistant", "content": content})
                return content
            self.messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": [
                {"id": c.id, "type": "function",
                 "function": {"name": c.function.name, "arguments": c.function.arguments}}
                for c in calls]})
            for c in calls:
                try:
                    args = json.loads(c.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = None
                out = tools.call(self.st, c.function.name, args) if args is not None else \
                    {"ok": False, "error": "arguments were not valid JSON"}
                self.messages.append({"role": "tool", "tool_call_id": c.id, "content": json.dumps(out)})
        raise RuntimeError("model kept calling tools without replying")
