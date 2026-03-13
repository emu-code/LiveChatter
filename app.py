import os
import time
import datetime
import streamlit as st
from speech import LiveTranscriber, LANGUAGES


st.set_page_config(page_title="LiveChatter", page_icon="🎙️", layout="centered")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:ital,wght@0,300;0,400;0,500;1,300&family=DM+Sans:wght@300;400;500&display=swap');

html, body, [class*="css"] {
  font-family: 'DM Sans', sans-serif;
  background-color: #0c0c0c;
  color: #e2e2e2;
}
#MainMenu, footer, header { visibility: hidden; }
.block-container { max-width: 700px; padding: 2.5rem 1.5rem; }

.ls-label {
  font-family: 'DM Mono', monospace;
  font-size: 0.72rem; letter-spacing: 0.22em;
  text-transform: uppercase; color: #555; margin-bottom: 0.25rem;
}
.ls-title {
  font-size: 2.6rem; font-weight: 300; color: #efefef;
  letter-spacing: -0.03em; margin-bottom: 0.1rem; line-height: 1.1;
}
.ls-title b { color: #4ade80; font-weight: 400; }
.ls-sub { font-size: 0.85rem; color: #555; margin-bottom: 2rem; font-weight: 300; }

.pill {
  display: inline-flex; align-items: center; gap: 0.45rem;
  padding: 0.28rem 0.9rem; border-radius: 999px;
  font-family: 'DM Mono', monospace;
  font-size: 0.72rem; letter-spacing: 0.1em; font-weight: 500;
  margin-bottom: 1.4rem;
}
.pill-idle   { background:#1a1a1a; color:#555; border:1px solid #262626; }
.pill-live   { background:#052e14; color:#4ade80; border:1px solid #15603a; }
.pill-paused { background:#1f1a00; color:#fbbf24; border:1px solid #5c4a00; }
.dot { width:7px; height:7px; border-radius:50%; display:inline-block; }
.dot-idle   { background:#3a3a3a; }
.dot-live   { background:#4ade80; animation:blink 1.4s infinite; }
.dot-paused { background:#fbbf24; }
@keyframes blink { 0%,100%{opacity:1} 50%{opacity:.25} }

.tx-card {
  background:#111; border:1px solid #1e1e1e; border-radius:10px;
  padding:1.2rem 1.4rem; min-height:220px; max-height:420px; overflow-y:auto;
  font-family:'DM Mono', monospace; font-size:0.88rem; line-height:1.75;
  color:#c8c8c8; white-space:normal; word-wrap:break-word; margin-bottom:1.2rem;
}
.tx-empty { color:#333; font-style:italic; }
.tx-interim { color:#666; font-style:italic; }

div.stButton > button {
  font-family:'DM Sans', sans-serif !important;
  font-size:0.82rem !important; font-weight:500 !important;
  border-radius:8px !important; height:2.5rem !important;
  border:1px solid #2a2a2a !important;
  background:#161616 !important; color:#c8c8c8 !important;
  transition:all .15s ease !important;
}
div.stButton > button:hover {
  background:#1f1f1f !important; border-color:#3a3a3a !important; color:#fff !important;
}
div.stButton > button:disabled { opacity:0.35 !important; cursor:not-allowed !important; }

div[data-baseweb="select"] > div {
  background:#111 !important; border-color:#222 !important;
  border-radius:8px !important; color:#ccc !important;
  font-family:'DM Mono', monospace !important; font-size:0.82rem !important;
}

.save-ok {
  font-family:'DM Mono', monospace; font-size:0.78rem;
  color:#4ade80; padding:0.5rem 0;
}
</style>
""", unsafe_allow_html=True)

# ── Session state 
DEFAULTS = {
    "transcriber": None,
    "running":     False,
    "paused":      False,
    "save_msg":    "",
    "save_time":   0.0,
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Shorthand 
t: LiveTranscriber = st.session_state.transcriber

# ── Header
st.markdown('<p class="ls-label">Deepgram · Real-time ASR</p>', unsafe_allow_html=True)
st.markdown('<h1 class="ls-title">Live<b>Chatter</b></h1>', unsafe_allow_html=True)
st.markdown('<p class="ls-sub">Speak. Transcribe. Save.</p>', unsafe_allow_html=True)

# ── Status 
if not st.session_state.running:
    pill = '<div class="pill pill-idle"><span class="dot dot-idle"></span>IDLE</div>'
elif st.session_state.paused:
    pill = '<div class="pill pill-paused"><span class="dot dot-paused"></span>PAUSED</div>'
else:
    pill = '<div class="pill pill-live"><span class="dot dot-live"></span>LIVE</div>'
st.markdown(pill, unsafe_allow_html=True)

# ── Language selector 
lang_name = st.selectbox(
    "Language",
    list(LANGUAGES.keys()),
    disabled=st.session_state.running,
    label_visibility="collapsed",
)
lang_code = LANGUAGES[lang_name]

def _build_display(lines):
    """Join lines into paragraphs — a '\n' sentinel starts a new paragraph."""
    paragraphs, current = [], []
    for line in lines:
        if line == "\n":
            if current:
                paragraphs.append(" ".join(current))
            current = []
        else:
            current.append(line)
    if current:
        paragraphs.append(" ".join(current))
    return "<br><br>".join(paragraphs)

final_text   = _build_display(t._lines) if t else ""
interim_text = t.interim    if t else ""

if final_text or interim_text:
    display = final_text
    if interim_text:
        display += f" <span class='tx-interim'>{interim_text}</span>"
    st.markdown(f'<div class="tx-card">{display}</div>', unsafe_allow_html=True)
else:
    st.markdown(
        '<div class="tx-card"><span class="tx-empty">Transcript will appear here…</span></div>',
        unsafe_allow_html=True,
    )


c1, c2, c3, c4 = st.columns(4)

with c1:
    if st.button("🎙 Start", disabled=st.session_state.running, use_container_width=True):
        transcriber = LiveTranscriber(language_code=lang_code)
        transcriber.start()
        st.session_state.transcriber = transcriber
        st.session_state.running     = True
        st.session_state.paused      = False
        st.session_state.save_msg    = ""
        st.rerun()

with c2:
    pause_label = "▶ Resume" if st.session_state.paused else "⏸ Pause"
    if st.button(pause_label, disabled=not st.session_state.running, use_container_width=True):
        if t:
            if st.session_state.paused:
                t.resume()
                st.session_state.paused = False
            else:
                t.pause()
                st.session_state.paused = True
        st.rerun()

with c3:
    if st.button("⏹ Stop", disabled=not st.session_state.running, use_container_width=True):
        if t:
            t.stop()
        st.session_state.running     = False
        st.session_state.paused      = False
        st.session_state.transcriber = None
        st.rerun()

with c4:
    no_text = not final_text.strip()
    if st.button("💾 Save", disabled=no_text, use_container_width=True):
        if t:
            path = t.save()
        else:
            ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.abspath(f"transcript_{ts}.txt")
            clean = _build_display(t._lines) if t else final_text
            clean = clean.replace("<br><br>", "\n\n")
            with open(path, "w", encoding="utf-8") as f:
                f.write(clean)
        st.session_state.save_msg  = f"✓ Saved → {path}"
        st.session_state.save_time = time.time()
        st.rerun()

if st.session_state.save_msg:
    st.markdown(
        f'<p class="save-ok">{st.session_state.save_msg}</p>',
        unsafe_allow_html=True,
    )

if st.session_state.running and not st.session_state.paused:
    time.sleep(0.8)
    st.rerun()
elif st.session_state.save_msg:
    elapsed = time.time() - st.session_state.save_time
    remaining = 2.0 - elapsed
    if remaining > 0:
        time.sleep(remaining)
    st.session_state.save_msg  = ""
    st.session_state.save_time = 0.0
    st.rerun()