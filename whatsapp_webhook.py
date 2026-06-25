import os
import uuid
import requests
import tempfile
import logging
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv
from fastapi import FastAPI, Request, BackgroundTasks
from twilio.rest import Client as TwilioClient
from sarvamai import SarvamAI
from groq import Groq
import traceback

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

# Environment variables
SARVAM_KEY = os.getenv("SARVAM_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_AUTH = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM")  # e.g. 'whatsapp:+14155238886'

logger.info("Initializing clients...")
logger.info(f"SARVAM_API_KEY configured: {bool(SARVAM_KEY)}")
logger.info(f"GROQ_API_KEY configured: {bool(GROQ_API_KEY)}")
logger.info(f"TWILIO_SID configured: {bool(TWILIO_SID)}")
logger.info(f"TWILIO_AUTH_TOKEN configured: {bool(TWILIO_AUTH)}")
logger.info(f"TWILIO_WHATSAPP_FROM: {TWILIO_WHATSAPP_FROM}")

# Clients
sarvam = SarvamAI(api_subscription_key=SARVAM_KEY)
twilio_client = TwilioClient(TWILIO_SID, TWILIO_AUTH)
groq_client = Groq(api_key=GROQ_API_KEY)

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
            model="saaras:v3",
            language_code="ta-IN"
        )
    transcript = getattr(resp, "transcript", None) or getattr(resp, "text", None)
    if not transcript:
        d = resp.model_dump() if hasattr(resp, "model_dump") else {}
        transcript = d.get("transcript") or d.get("text") or ""
    return transcript.strip()

def groq_fact_check(transcript: str) -> str:
    """Call Groq Compound (with live web search) to fact-check and return result."""
    prompt = f"""
You are an expert fact-checker for Indian and Tamil Nadu news.
Search the web for the latest and most credible sources related to this claim.

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
    response = groq_client.chat.completions.create(
        model="groq/compound",  # Groq Compound with built-in live web search (updated from compound-beta)
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content

def send_whatsapp_reply(to: str, text: str):
    """Send WhatsApp message via Twilio REST API."""
    twilio_client.messages.create(
        from_=TWILIO_WHATSAPP_FROM,
        to=to,
        body=text
    )

def process_incoming(from_number: str, body: str, num_media: str, media_url: str):
    """
    Full processing pipeline:
      - If media present: download -> Sarvam ASR -> transcript
      - else: use text body
      - Groq Compound fact-check (with live web search)
      - send reply via Twilio
    """
    local_path = None
    try:
        logger.info(f"Processing incoming message from: {from_number}. NumMedia: {num_media}, MediaUrl: {media_url}")
        if num_media and int(num_media) > 0 and media_url:
            logger.info("Downloading media from Twilio...")
            local_path = download_media(media_url)
            logger.info(f"Media downloaded to {local_path}. Starting transcription via Sarvam AI...")
            transcript = sarvam_transcribe(local_path)
            logger.info(f"ASR transcription result: '{transcript}'")
        else:
            transcript = (body or "").strip()
            logger.info(f"No media. Using text body: '{transcript}'")

        if not transcript:
            reply = "தகவல் கிடைக்கவில்லை — தயவுசெய்து தெளிவாக ஒரு voice note அனுப்பவும்."
            logger.warning("No text or audio transcription resolved. Sending empty transcript reply.")
            send_whatsapp_reply(from_number, reply)
            return

        logger.info("Initiating Groq Fact-Check compound model run...")
        fact_result = groq_fact_check(transcript)
        logger.info(f"Groq Fact-Check completed successfully: Verdict summary: \n{fact_result}")
        send_whatsapp_reply(from_number, f"Transcript:\n{transcript}\n\nFact-check:\n{fact_result}")
        logger.info("Reply successfully sent back to user.")

    except Exception as e:
        error_msg = f"Processing error: {type(e).__name__} - {e}\n{traceback.format_exc()}"
        logger.error(error_msg)
        try:
            send_whatsapp_reply(from_number, "சமையலில் பிழை: பிறகு முயற்சிக்கவும்.")
        except Exception as send_err:
            logger.error(f"Failed to send failure reply: {send_err}")

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
    """
    Twilio will POST form-encoded data to this endpoint.
    We'll enqueue the processing as a background task to avoid webhook timeouts.
    """
    form = await request.form()
    logger.info(f"Incoming webhook data: {dict(form)}")
    from_number = form.get("From")
    body = form.get("Body", "")
    num_media = form.get("NumMedia", "0")
    media_url = form.get("MediaUrl0")
    background_tasks.add_task(process_incoming, from_number, body, num_media, media_url)
    return {"status": "accepted"}