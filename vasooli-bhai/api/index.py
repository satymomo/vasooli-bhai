"""Vasooli Bhai API. Vercel runs this file as a serverless function; server.py
reuses it locally.

The server is stateless: the browser sends the demo state with each request
and gets the updated state back. Tool arguments are still validated here, and
the Sarvam key (SARVAM_API_KEY) never leaves the server.
"""
import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(__file__))
import _agent as agent  # noqa: E402
import _tools as tools  # noqa: E402

TTS_SPEAKER = os.environ.get("SARVAM_TTS_SPEAKER", "shubh")
_client = None


def key():
    return os.environ.get("SARVAM_API_KEY", "").strip()


def client():
    global _client
    if _client is None:
        from sarvamai import SarvamAI
        _client = SarvamAI(api_subscription_key=key())
    return _client


def fresh(mode):
    st = tools.new_state()
    st.update(mode="live" if mode == "live" and key() else "demo", transcript=[])
    return st


def load(st):
    if not (isinstance(st, dict) and isinstance(st.get("invoice"), dict)
            and isinstance(st.get("events"), list) and isinstance(st.get("transcript"), list)):
        raise ValueError("missing or invalid demo state; reset the demo")
    if st.get("mode") == "live" and not key():
        st["mode"] = "demo"
    st["events"] = st["events"][-50:]
    st["transcript"] = st["transcript"][-60:]
    return st


def make_agent(st):
    return agent.LLMAgent(client(), st) if st["mode"] == "live" else agent.ScriptedAgent(st)


def stt(audio, mime):
    mime = (mime or "audio/webm").split(";")[0].strip()  # API rejects "audio/webm;codecs=opus"
    codec = "webm" if "webm" in mime else "ogg" if "ogg" in mime else "mp4" if "mp4" in mime else "wav"
    r = client().speech_to_text.transcribe(
        file=("speech." + codec, audio, mime),
        model="saaras:v3", mode="codemix", input_audio_codec=codec)
    return (r.transcript or "").strip()


def tts(text):
    r = client().text_to_speech.convert(
        text=text, language_code="hi-IN", speaker=TTS_SPEAKER, model="bulbul:v3")
    return "".join(r.audios)  # base64 wav


def route(method, path, body, ctype):
    """Returns (status, json_dict)."""
    action = path.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
    if method == "GET" and action == "config":
        return 200, {"key_configured": bool(key()), "today": tools.today().isoformat()}
    if method != "POST":
        return 404, {"error": "not found"}

    if action == "stt":
        if not key():
            return 409, {"error": "Sarvam key not configured"}
        return 200, {"text": stt(body, ctype)}

    data = json.loads(body or b"{}")
    if action == "reset":
        return 200, {"state": fresh(data.get("mode"))}
    if action == "tts":
        if not key():
            return 409, {"error": "Sarvam key not configured"}
        return 200, {"audio": tts((data.get("text") or "")[:1000])}

    st = load(data.get("state"))
    if action == "start":
        st.update(fresh(st["mode"]))
        reply = make_agent(st).opening()
    elif action == "turn":
        text = (data.get("text") or "").strip()[:500]
        if not text:
            return 400, {"error": "empty message"}
        st["transcript"].append({"role": "client", "text": text})
        reply = make_agent(st).reply(text)
    else:
        return 404, {"error": "not found"}
    st["transcript"].append({"role": "agent", "text": reply})
    return 200, {"state": st, "reply": reply}


class handler(BaseHTTPRequestHandler):
    def _run(self, method):
        try:
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0)) if method == "POST" else b""
            code, out = route(method, self.path, body, self.headers.get("Content-Type", ""))
        except ValueError as e:
            code, out = 400, {"error": str(e)[:300]}
        except Exception as e:  # surface real failures; never pretend success
            traceback.print_exc()
            code, out = 502, {"error": f"{type(e).__name__}: {e}"[:300]}
        data = json.dumps(out).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._run("GET")

    def do_POST(self):
        self._run("POST")

    def log_message(self, fmt, *a):
        pass
