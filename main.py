from sarvamai import SarvamAI
import google.generativeai as genai
import os
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Get API keys from environment variables
SARVAM_KEY = os.getenv("SARVAM_API_KEY")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

# ---------------- Sarvam AI Setup ----------------
client = SarvamAI(api_subscription_key=SARVAM_KEY)

# Transcribe short Tamil audio
with open("your_file.wav", "rb") as audio_file:
    response = client.speech_to_text.transcribe(
        file=audio_file,
        model="saarika:v2.5",
        language_code="ta-IN"
    )

# Get transcript
transcript = getattr(response, "transcript", None) or getattr(response, "text", None)
print("Transcript:", transcript)

# ---------------- Gemini Fact-Check ----------------
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

fact_check_prompt = f"""
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
Verdict: [TRUE / FALSE / PARTIALLY TRUE / UNCERTAIN]
Explanation: [2-3 lines in Tamil]
"""

response = model.generate_content(fact_check_prompt)
print("\n--- FACT CHECK RESULT ---")
print(response.text)
