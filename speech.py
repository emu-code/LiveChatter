import os
import json
import asyncio
import threading
import queue
import time
import datetime
import pyaudio
import websockets
from dotenv import load_dotenv

load_dotenv()

RATE     = 16000
CHUNK    = 8192
CHANNELS = 1
FORMAT   = pyaudio.paInt16

LANGUAGES = {
    "English (US)":       "en-US",
    "English (UK)":       "en-GB",
    "Spanish":            "es",
    "French":             "fr",
    "German":             "de",
    "Italian":            "it",
    "Portuguese":         "pt",
    "Dutch":              "nl",
    "Hindi":              "hi",
    "Japanese":           "ja",
    "Chinese (Mandarin)": "zh",
    "Korean":             "ko",
    "Russian":            "ru",
    "Arabic":             "ar",
}


class LiveTranscriber:
    def __init__(self, language_code="en-US", on_transcript=None):
        self.language_code = language_code
        self.on_transcript = on_transcript  

        self._lines      = []         
        self._interim    = ""          
        self._last_final = None        
        self._lock       = threading.Lock()
        self._muted   = False
        self._running = False
        self._ready   = threading.Event()
        self._audio_q    = queue.Queue()
        self._session_th = None
        self._pa         = None
        self._stream     = None

    def start(self):
        if self._running:
            return
        self._api_key = os.getenv("DEEPGRAM_API_KEY", "")
        if not self._api_key:
            raise ValueError("DEEPGRAM_API_KEY not set in .env file.")

        self._running = True
        self._muted   = False
        self._ready.clear()

        self._session_th = threading.Thread(
            target=self._thread_main, daemon=True
        )
        self._session_th.start()

        if not self._ready.wait(timeout=10):
            self._running = False
            raise ConnectionError("Timed out connecting to Deepgram.")

    def pause(self):
        self._muted = True

    def resume(self):
        self._muted = False

    def stop(self):
        if not self._running:
            return
        self._running = False
        self._audio_q.put(None)

        if self._stream:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
        if self._pa:
            try:
                self._pa.terminate()
            except Exception:
                pass
        if self._session_th:
            self._session_th.join(timeout=5)

    def save(self, filepath=""):
        if not filepath:
            ts       = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = f"transcript_{ts}.txt"
        filepath = os.path.abspath(filepath)
        with self._lock:
            body = "\n".join(self._lines)
        header = (
            f"Deepgram Live Transcript\n"
            f"Language : {self.language_code}\n"
            f"Saved    : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"{'─' * 44}\n\n"
        )
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(header + body)
        return filepath

    @property
    def is_running(self): return self._running
    @property
    def is_paused(self):  return self._muted
    @property
    def transcript(self):
        """All finalised lines as a single string."""
        with self._lock:
            return "\n".join(self._lines)
    @property
    def interim(self):
        """Latest interim (in-progress) line."""
        with self._lock:
            return self._interim

    def _thread_main(self):
        """Runs a fresh asyncio event loop in the background thread."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._session(loop))
        except Exception as e:
            print(f"❌  Session error: {e}")
            self._ready.set()
        finally:
            loop.close()

    async def _session(self, loop):
        url = (
            f"wss://api.deepgram.com/v1/listen"
            f"?encoding=linear16"
            f"&sample_rate={RATE}"
            f"&channels={CHANNELS}"
            f"&model=nova-2"
            f"&language={self.language_code}"
            f"&smart_format=true"
            f"&interim_results=true"
            f"&utterance_end_ms=1000"
            f"&vad_events=true"
        )
        headers = {"Authorization": f"Token {self._api_key}"}

        async with websockets.connect(url, additional_headers=headers) as ws:
            print("✅  Connected to Deepgram.")

            self._pa = pyaudio.PyAudio()

            def audio_callback(in_data, frame_count, time_info, status):
                if not self._muted and self._running and in_data:
                    self._audio_q.put(in_data)
                return (None, pyaudio.paContinue)

            self._stream = self._pa.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                input=True,
                frames_per_buffer=CHUNK,
                stream_callback=audio_callback,
            )
            self._stream.start_stream()
            self._ready.set()

            # Run sender + receiver concurrently
            await asyncio.gather(
                self._sender(ws, loop),
                self._receiver(ws),
            )

    async def _sender(self, ws, loop):
        """Drains the threading.Queue and sends audio to Deepgram."""
        while self._running:
            try:
                # Poll the thread-safe queue without blocking the event loop
                data = await loop.run_in_executor(
                    None, lambda: self._audio_q.get(timeout=0.5)
                )
                if data is None:   
                    break
                await ws.send(data)
            except queue.Empty:
                continue
            except Exception:
                break

    async def _receiver(self, ws):
        """Receives and parses transcripts from Deepgram."""
        async for raw in ws:
            if not self._running:
                break
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type", "")

            if msg_type != "Results":
                continue

            try:
                text        = msg["channel"]["alternatives"][0]["transcript"]
                is_final    = msg.get("is_final", False)
                speech_final = msg.get("speech_final", False)
            except (KeyError, IndexError):
                continue

            if not text:
                continue

            with self._lock:
                if is_final:
                    self._lines.append(text)
                    if speech_final:
                        self._lines.append("\n")
                    self._last_final = time.time()
                    self._interim    = ""
                else:
                    self._interim = text

            if self.on_transcript:
                self.on_transcript(text, is_final)
            else:
                label = "[FINAL]  " if is_final else "[INTERIM]"
                print(f"{label} {text}")

def _pick_language():
    names = list(LANGUAGES.keys())
    print("\nAvailable languages:")
    for i, name in enumerate(names, 1):
        print(f"  {i:>2}.  {name}")
    while True:
        raw = input(f"\nChoose [1–{len(names)}] (default 1): ").strip()
        idx = int(raw) if raw.isdigit() else 1
        if 1 <= idx <= len(names):
            name = names[idx - 1]
            code = LANGUAGES[name]
            print(f"→  Using: {name} ({code})\n")
            return code
        print(f"   Enter a number between 1 and {len(names)}.")


def main():
    print("═" * 45)
    print("  LiveScribe — Deepgram Live Transcription  ")
    print("═" * 45)
    lang = _pick_language()
    t    = LiveTranscriber(language_code=lang)
    print("Commands (press ENTER after each):")
    print("  p  → pause / resume")
    print("  s  → save transcript")
    print("  q  → quit\n")
    t.start()
    print("🎙️  Listening…\n")
    try:
        while True:
            cmd = input("").strip().lower()
            if cmd == "p":
                if t.is_paused:
                    t.resume(); print("▶️   Resumed.")
                else:
                    t.pause();  print("⏸️   Paused.")
            elif cmd == "s":
                print(f"💾  Saved → {t.save()}")
            elif cmd == "q":
                break
    except KeyboardInterrupt:
        pass
    finally:
        t.stop()
        if input("\nSave before exit? [y/N]: ").strip().lower() == "y":
            print(f"💾  Saved → {t.save()}")
        print("👋  Goodbye.")


if __name__ == "__main__":
    main()