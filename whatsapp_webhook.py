import os
import uuid
import requests
import tempfile
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv
from fastapi import FastAPI, Request, BackgroundTasks
from twilio.rest import Client as TwilioClient
from sarvamai import SarvamAI
from google import genai
import traceback

load_dotenv()

# Environment variables
SARVAM_KEY = os.getenv("SARVAM_API_KEY")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_AUTH = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM")

# Clients
sarvam = SarvamAI(api_subscription_key=SARVAM_KEY)
twilio_client = TwilioClient(TWILIO_SID, TWILIO_AUTH)

# New Google GenAI SDK
gemini_client = genai.Client(api_key=GEMINI_KEY)
GEMINI_MODEL = "gemini-2.0-flash"

app = FastAPI()

def download_media(url: str) -> str:
    """Download media URL from Twilio with Basic Auth and save to temp file."""
    auth = HTTPBasicAuth(TWILIO_SID, TWILIO_AUTH)
    resp = requests.get(url, auth=auth)
    resp.raise_for_status()

    ct = resp.headers.get("Content-Type", "")
    ext = ".bin"
    if "opus" in ct or "ogg" in ct:
        ext = ".opus"
    elif "wav" in ct:
        ext = ".wav"
    elif "mpeg" in ct or "mp3" in ct:
        ext = ".mp3"

    temp_dir = tempfile.gettempdir()
    path = os.path.join(temp_dir, f"{uuid.uuid4().hex}{ext}")

    with open(path, "wb") as f:
        f.write(resp.content)
    return path

def sarvam_transcribe(file_path: str) -> str:
    """Call Sarvam ASR and return the transcript (Tamil)."""
    with open(file_path, "rb") as fh:
        resp = sarvam.speech_to_text.transcribe(
            file=fh,
            model="saaras:v3",  # Updated from deprecated saarika:v2.5
            language_code="ta-IN"
        )
    transcript = getattr(resp, "transcript", None) or getattr(resp, "text", None)
    if not transcript:
        d = resp.model_dump() if hasattr(resp, "model_dump") else {}
        transcript = d.get("transcript") or d.get("text") or ""
    return transcript.strip()

def gemini_fact_check(transcript: str) -> str:
    """Call Gemini to fact-check the transcript and return formatted result."""
    prompt = f"""
You are an expert fact-checker for Indian and Tamil Nadu news.
You have access to the latest news up to this moment.

Fact to verify:
"{transcript}"

Tasks:
1. Search for the latest and most credible news sources related to this fact.
2. Determine if the statement is TRUE, FALSE, or PARTIALLY TRUE.
3. Provide a short, clear explanation in Tamil, citing the sources or reasoning.
4. If unsure, say "தகவல் போதுமானதாக இல்லை" (Insufficient information).

Format:
Verdict: [TRUE✅ / FALSE❌ / PARTIALLY TRUE 🆗/ UNCERTAIN🐟]
Explanation: [2-3 lines in Tamil]
"""
    resp = gemini_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt
    )
    return resp.text

def send_whatsapp_reply(to: str, text: str):
    """Send WhatsApp message via Twilio REST API."""
    twilio_client.messages.create(
        from_=TWILIO_WHATSAPP_FROM,
        to=to,
        body=text
    )

def process_incoming(from_number: str, body: str, num_media: str, media_url: str):
    local_path = None
    try:
        if num_media and int(num_media) > 0 and media_url:
            local_path = download_media(media_url)
            transcript = sarvam_transcribe(local_path)
        else:
            transcript = (body or "").strip()

        if not transcript:
            reply = "தகவல் கிடைக்கவில்லை — தயவுசெய்து தெளிவாக ஒரு voice note அனுப்பவும்."
            send_whatsapp_reply(from_number, reply)
            return

        fact_result = gemini_fact_check(transcript)
        send_whatsapp_reply(from_number, f"Transcript:\n{transcript}\n\nFact-check:\n{fact_result}")

    except Exception as e:
        error_msg = f"Processing error: {type(e).__name__} - {e}\n{traceback.format_exc()}"
        print(error_msg)
        send_whatsapp_reply(from_number, "சமையலில் பிழை: பிறகு முயற்சிக்கவும்.")

    finally:
        if local_path and os.path.exists(local_path):
            try:
                os.remove(local_path)
            except Exception:
                pass


@app.get("/")
async def root():
    return {"message": "WhatsApp Fake News Checker API is live!"}

@app.post("/twilio-webhook")
async def twilio_webhook(request: Request, background_tasks: BackgroundTasks):
    form = await request.form()
    print("Incoming webhook data:", dict(form))
    from_number = form.get("From")
    body = form.get("Body", "")
    num_media = form.get("NumMedia", "0")
    media_url = form.get("MediaUrl0")
    background_tasks.add_task(process_incoming, from_number, body, num_media, media_url)
    return {"status": "accepted"}