from twilio.rest import Client
import os
from dotenv import load_dotenv

load_dotenv()

sid = os.getenv("TWILIO_SID")
token = os.getenv("TWILIO_AUTH_TOKEN")
client = Client(sid, token)

try:
    message = client.messages.create(
        from_='whatsapp:+14155238886',
        to='whatsapp:',  # Replace with your number
        body="Test message from Twilio API"
    )
    print("Message sent! SID:", message.sid)
except Exception as e:
    print("Error sending message:", e)
