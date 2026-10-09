"""Snap & Study — explain problems, diagrams, and notes with Gemini."""
from __future__ import annotations

import os
import re
from urllib.parse import quote

import streamlit as st
from google import genai
from google.genai import types

from prompts import SYSTEM_PROMPT, WELCOME_MESSAGE_TEMPLATE, SUMMARY_REQUEST_PROMPT

MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
st.set_page_config(page_title="Snap & Study", page_icon="📚", layout="centered")


def get_secret(name: str, default: str = "") -> str:
    """Read a Streamlit secret first, then an environment variable."""
    try:
        value = st.secrets.get(name, "")
    except Exception:
        value = ""
    return str(value or os.getenv(name, default)).strip()


GEMINI_API_KEY = get_secret("GEMINI_API_KEY")


@st.cache_resource
def get_gemini_client(api_key: str):
    return genai.Client(api_key=api_key)


def render_message(message: dict) -> None:
    with st.chat_message(message["role"]):
        if message.get("kind") == "image":
            st.image(message["content"], caption="Uploaded study material", use_container_width=True)
        else:
            st.markdown(message["content"])


def add_message(role: str, kind: str, content) -> None:
    st.session_state.messages.append({"role": role, "kind": kind, "content": content})
    render_message(st.session_state.messages[-1])


def ask_gemini(parts: list) -> str:
    try:
        response = st.session_state.chat.send_message(parts)
        answer = getattr(response, "text", None)
        return answer.strip() if answer else "I couldn't read a clear explanation from that. Try a sharper photo or add a little context."
    except Exception as error:
        # Don't expose credentials; errors are useful for local debugging but should be brief in the UI.
        st.error("Gemini couldn't process that request. Check your API key, internet connection, and model access, then try again.")
        return "I couldn't generate the explanation this time. Please try again with a clearer image or a shorter question."


def safe_text(text: str, limit: int = 3500) -> str:
    text = re.sub(r"\n{3,}", "\n\n", (text or "").strip())
    return text[:limit] + ("…" if len(text) > limit else "")


def build_share_links(explanation: str) -> tuple[str, str, str]:
    title = "Snap & Study — Study explanation"
    payload = f"{title}\n\n{safe_text(explanation)}"
    encoded = quote(payload)
    whatsapp_url = f"https://wa.me/?text={encoded}"
    telegram_url = f"https://t.me/share/url?url=&text={encoded}"
    mailto_url = f"mailto:?subject={quote(title)}&body={encoded}"
    return whatsapp_url, telegram_url, mailto_url


def send_whatsapp_via_twilio(to_number: str, body: str) -> tuple[bool, str]:
    """Optional direct WhatsApp delivery for projects configured with Twilio."""
    from twilio.rest import Client

    sid = get_secret("TWILIO_ACCOUNT_SID")
    token = get_secret("TWILIO_AUTH_TOKEN")
    sender = get_secret("TWILIO_WHATSAPP_FROM")
    if not all([sid, token, sender]):
        return False, "Direct sending isn't configured. Use the WhatsApp share link instead, or add Twilio credentials to Streamlit secrets."
    try:
        client = Client(sid, token)
        message = client.messages.create(
            from_=sender if sender.startswith("whatsapp:") else f"whatsapp:{sender}",
            to=to_number if to_number.startswith("whatsapp:") else f"whatsapp:{to_number}",
            body=body[:1500],
        )
        return True, message.sid
    except Exception as error:
        return False, f"Twilio couldn't send the message: {error}"


# Step 1 — onboarding mirrors MacroSnap's flow.
if "onboarded" not in st.session_state:
    st.title("📚 Snap & Study")
    st.caption("Snap what confuses you. Understand it. Save the explanation.")
    st.markdown("Turn a tricky question, diagram, or page of notes into a clear, step-by-step explanation.")
    with st.form("onboarding_form"):
        name = st.text_input("Your name", placeholder="e.g. Alex")
        preferred_channel = st.selectbox(
            "Where do you usually save study notes?",
            ["WhatsApp", "Telegram", "Email"],
        )
        submitted = st.form_submit_button("Let's study!", use_container_width=True)
    if submitted:
        if not name.strip():
            st.warning("Please enter your name to get started.")
        elif not GEMINI_API_KEY:
            st.error("Gemini API key not found. Add GEMINI_API_KEY to .streamlit/secrets.toml or your environment variables, then rerun the app.")
        else:
            st.session_state.name = name.strip()
            st.session_state.preferred_channel = preferred_channel
            st.session_state.chat = get_gemini_client(GEMINI_API_KEY).chats.create(
                model=MODEL_NAME,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.35,
                ),
            )
            st.session_state.messages = []
            st.session_state.last_explanation = ""
            st.session_state.onboarded = True
            st.rerun()
    with st.expander("What you can upload"):
        st.write("A maths problem, science diagram, textbook page, handwritten notes, code snippet, or any concept you want explained.")
    st.stop()

# Step 2 — chat and share actions.
header_col, reset_col = st.columns([5, 1], vertical_alignment="center")
with header_col:
    st.title("📚 Snap & Study")
with reset_col:
    if st.button("Restart", help="Start a new study session"):
        for key in ("onboarded", "name", "preferred_channel", "chat", "messages", "last_explanation"):
            st.session_state.pop(key, None)
        st.rerun()

st.caption(f"Studying with {st.session_state.name} · Save explanations to {st.session_state.preferred_channel}")

if not st.session_state.messages:
    add_message("assistant", "text", WELCOME_MESSAGE_TEMPLATE.format(name=st.session_state.name))
else:
    for message in st.session_state.messages:
        render_message(message)

with st.sidebar:
    st.subheader("How it works")
    st.markdown("1. **Snap:** upload a problem, diagram, or notes.\n2. **Understand:** Gemini explains it simply.\n3. **Save:** share the explanation to WhatsApp, Telegram, or email.")
    st.divider()
    st.caption("Tip: take the photo in good light and make sure all text is visible.")

user_input = st.chat_input(
    "Ask a question or attach a photo of your study material…",
    accept_file=True,
    file_type=["jpg", "jpeg", "png", "webp"],
)

if user_input:
    parts = []
    photo = user_input.files[0] if user_input.files else None
    text = (user_input.text or "").strip()

    if photo is not None:
        photo_bytes = photo.getvalue()
        mime_type = photo.type or "image/jpeg"
        add_message("user", "image", photo_bytes)
        parts.append(types.Part.from_bytes(data=photo_bytes, mime_type=mime_type))
    if text:
        add_message("user", "text", text)
        parts.append(text)
    elif photo is not None:
        parts.append("Explain the problem, diagram, or notes in this image using your structured teaching instructions.")

    if parts:
        with st.spinner("Breaking it down into simple steps…"):
            answer = ask_gemini(parts)
        st.session_state.last_explanation = answer
        add_message("assistant", "text", answer)

# Sharing works on the latest generated explanation and keeps the pattern simple.
explanation = st.session_state.get("last_explanation", "")
if explanation:
    st.divider()
    st.subheader("Save this explanation")
    st.caption("Choose an option to open a prefilled message. Review it and press Send in the selected app.")
    whatsapp_url, telegram_url, mailto_url = build_share_links(explanation)
    c1, c2, c3 = st.columns(3)
    with c1:
        st.link_button("📲 WhatsApp", whatsapp_url, use_container_width=True)
    with c2:
        st.link_button("✈️ Telegram", telegram_url, use_container_width=True)
    with c3:
        st.link_button("✉️ Email", mailto_url, use_container_width=True)

    with st.expander("Optional: send directly with Twilio WhatsApp"):
        st.caption("This sends a WhatsApp message through your configured Twilio sandbox/number. Share links above do not need Twilio credentials.")
        to_number = st.text_input("Recipient WhatsApp number", placeholder="+91XXXXXXXXXX", key="twilio_to_number")
        if st.button("Send directly with Twilio", use_container_width=True):
            if not to_number.strip():
                st.warning("Enter a recipient number, including country code.")
            else:
                with st.spinner("Sending to WhatsApp…"):
                    ok, detail = send_whatsapp_via_twilio(to_number.strip(), f"Snap & Study explanation\n\n{safe_text(explanation, 1400)}")
                if ok:
                    st.success("Message sent to WhatsApp.")
                else:
                    st.error(detail)

    st.download_button(
        "⬇️ Download explanation as .txt",
        data=explanation,
        file_name="snap-and-study-explanation.txt",
        mime="text/plain",
    )
