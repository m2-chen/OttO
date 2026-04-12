"""
src/agent/email_agent.py
Post-booking email agent for OttO.

Sends two emails after a successful booking:
  1. Advisor briefing — internal note with customer context and AI-written summary
  2. Customer confirmation — booking details, advisor name, dealership address + directions
"""

import os
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from openai import OpenAI

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ADVISOR_EMAIL  = "mehdichenini8@gmail.com"
CUSTOMER_EMAIL_FALLBACK = "mehdichenini3@gmail.com"  # fallback if modal is skipped

DEALERSHIP_NAME    = "EV Land Paris"
DEALERSHIP_ADDRESS = "15 Avenue de la Grande Armée, 75016 Paris"
DEALERSHIP_MAPS    = "https://maps.google.com/?q=15+Avenue+de+la+Grande+Armée,+75016+Paris"
DEALERSHIP_PHONE   = "+33 (0)1 47 23 85 60"


# ---------------------------------------------------------------------------
# AI-generated advisor briefing
# ---------------------------------------------------------------------------

def generate_advisor_briefing(transcript: list[str], booking: dict) -> str:
    """
    Call OpenAI to produce a short, natural advisor briefing from the transcript.
    Returns a plain-text paragraph the advisor can read before the appointment.
    """
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    conversation = "\n".join(transcript) if transcript else "No transcript available."

    prompt = f"""You are writing a confidential internal briefing note for a car dealership sales advisor.
The advisor named {booking.get('staff_name', 'the advisor')} has an upcoming appointment with a customer.
Below is the transcript of the voice conversation between OttO (the AI receptionist) and the customer.

Write two short paragraphs the advisor will read before the meeting:

**Paragraph 1 — Customer context:**
Why the customer is coming in, what vehicle they are interested in or what issue they described,
their preferences and priorities, and any personal details that help the advisor connect with them.
Write it directly and warmly — as if briefing a trusted colleague. No bullet points.
Start with the customer's name if known.

**Paragraph 2 — Negotiation intelligence:**
Based on signals in the conversation, give the advisor a quiet edge. Cover:
- Price sensitivity: did they mention budget freely or guard it? Did they ask about deals or discounts?
- Decision structure: are they deciding alone or with a partner?
- Urgency: are they browsing or ready to move? Any timeline mentioned?
- Buyer type: analytical (lots of technical questions) or emotional (excited, vision-driven)?
- Any competitive awareness: did they mention other dealerships or compare prices?
- Recommended approach: one concrete tactical suggestion for how the advisor should open or steer the conversation.
Write this paragraph as a candid colleague-to-colleague note. Be direct and specific — vague observations are useless.
If the transcript does not contain enough signal for a specific insight, say so honestly rather than fabricating one.

Transcript:
{conversation}

Booking details:
- Date/time: {booking.get('slot_datetime', 'TBD')}
- Appointment type: {booking.get('appointment_type', 'TBD')}
- Advisor: {booking.get('staff_name', 'TBD')}
- Customer name: {booking.get('customer_name', 'TBD')}
- Customer phone: {booking.get('customer_phone', 'TBD')}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=300,
        temperature=0.7,
    )
    return response.choices[0].message.content.strip()


# ---------------------------------------------------------------------------
# Email sending
# ---------------------------------------------------------------------------

def _send_email(to: str, subject: str, html_body: str) -> None:
    """Send an email via Gmail SMTP."""
    sender    = ADVISOR_EMAIL
    app_pass  = os.getenv("GMAIL_APP_PASSWORD")

    if not app_pass:
        log.warning("GMAIL_APP_PASSWORD not set — email not sent.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"OttO — EV Land <{sender}>"
    msg["To"]      = to
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, app_pass)
            server.sendmail(sender, to, msg.as_string())
        log.info(f"Email sent to {to}: {subject}")
    except Exception as e:
        log.error(f"Failed to send email to {to}: {e}")


def send_advisor_email(booking: dict, briefing: str) -> None:
    """Send the internal advisor briefing email."""
    dt     = booking.get("slot_datetime", "TBD")
    name   = booking.get("customer_name", "Unknown")
    phone  = booking.get("customer_phone", "—")
    appt   = booking.get("appointment_type", "appointment").replace("_", " ").title()
    advisor = booking.get("staff_name", "Advisor")

    subject = f"Upcoming {appt} — {name} — {dt}"

    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; color: #1a1a1a;">
        <div style="background: #0a0a0a; padding: 24px 32px; border-radius: 8px 8px 0 0;">
            <span style="color: #ffffff; font-size: 22px; font-weight: 700; letter-spacing: 1px;">OttO</span>
            <span style="color: #888; font-size: 13px; margin-left: 8px;">— EV Land Paris</span>
        </div>
        <div style="background: #f9f9f9; padding: 32px; border-radius: 0 0 8px 8px; border: 1px solid #e5e5e5; border-top: none;">
            <p style="font-size: 13px; color: #888; margin: 0 0 4px;">INTERNAL BRIEFING</p>
            <h2 style="margin: 0 0 24px; font-size: 20px;">Upcoming appointment — {name}</h2>

            <table style="width: 100%; border-collapse: collapse; margin-bottom: 24px;">
                <tr>
                    <td style="padding: 8px 0; color: #555; font-size: 14px; width: 140px;">Date &amp; Time</td>
                    <td style="padding: 8px 0; font-weight: 600; font-size: 14px;">{dt}</td>
                </tr>
                <tr>
                    <td style="padding: 8px 0; color: #555; font-size: 14px;">Appointment type</td>
                    <td style="padding: 8px 0; font-weight: 600; font-size: 14px;">{appt}</td>
                </tr>
                <tr>
                    <td style="padding: 8px 0; color: #555; font-size: 14px;">Advisor</td>
                    <td style="padding: 8px 0; font-weight: 600; font-size: 14px;">{advisor}</td>
                </tr>
                <tr>
                    <td style="padding: 8px 0; color: #555; font-size: 14px;">Customer name</td>
                    <td style="padding: 8px 0; font-weight: 600; font-size: 14px;">{name}</td>
                </tr>
                <tr>
                    <td style="padding: 8px 0; color: #555; font-size: 14px;">Customer phone</td>
                    <td style="padding: 8px 0; font-weight: 600; font-size: 14px;">{phone}</td>
                </tr>
            </table>

            <div style="background: #ffffff; border-left: 3px solid #0a0a0a; padding: 16px 20px; border-radius: 0 6px 6px 0; margin-bottom: 16px;">
                <p style="font-size: 13px; color: #888; margin: 0 0 8px; text-transform: uppercase; letter-spacing: 0.5px;">Customer context &amp; negotiation intelligence</p>
                <p style="font-size: 15px; line-height: 1.7; margin: 0; color: #1a1a1a; white-space: pre-line;">{briefing}</p>
            </div>

            <p style="font-size: 12px; color: #aaa; margin: 0;">Generated by OttO · EV Land Paris · Do not reply to this email</p>
        </div>
    </div>
    """
    _send_email(ADVISOR_EMAIL, subject, html)


def send_customer_email(booking: dict, customer_email: str = CUSTOMER_EMAIL_FALLBACK) -> None:
    """Send the booking confirmation email to the customer."""
    dt      = booking.get("slot_datetime", "TBD")
    name    = booking.get("customer_name", "Valued customer")
    appt    = booking.get("appointment_type", "appointment").replace("_", " ").title()
    advisor = booking.get("staff_name", "our team")

    subject = f"Your {appt} at EV Land — {dt}"

    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; color: #1a1a1a;">
        <div style="background: #0a0a0a; padding: 24px 32px; border-radius: 8px 8px 0 0;">
            <span style="color: #ffffff; font-size: 22px; font-weight: 700; letter-spacing: 1px;">OttO</span>
            <span style="color: #888; font-size: 13px; margin-left: 8px;">— EV Land Paris</span>
        </div>
        <div style="background: #f9f9f9; padding: 32px; border-radius: 0 0 8px 8px; border: 1px solid #e5e5e5; border-top: none;">
            <h2 style="margin: 0 0 8px; font-size: 20px;">Your appointment is confirmed.</h2>
            <p style="color: #555; margin: 0 0 28px; font-size: 15px;">Hi {name}, we look forward to seeing you at EV Land.</p>

            <table style="width: 100%; border-collapse: collapse; margin-bottom: 28px;">
                <tr>
                    <td style="padding: 8px 0; color: #555; font-size: 14px; width: 140px;">Date &amp; Time</td>
                    <td style="padding: 8px 0; font-weight: 600; font-size: 14px;">{dt}</td>
                </tr>
                <tr>
                    <td style="padding: 8px 0; color: #555; font-size: 14px;">Appointment</td>
                    <td style="padding: 8px 0; font-weight: 600; font-size: 14px;">{appt}</td>
                </tr>
                <tr>
                    <td style="padding: 8px 0; color: #555; font-size: 14px;">Your advisor</td>
                    <td style="padding: 8px 0; font-weight: 600; font-size: 14px;">{advisor}</td>
                </tr>
            </table>

            <div style="background: #ffffff; border: 1px solid #e5e5e5; border-radius: 6px; padding: 20px; margin-bottom: 24px;">
                <p style="font-size: 13px; color: #888; margin: 0 0 8px; text-transform: uppercase; letter-spacing: 0.5px;">How to find us</p>
                <p style="font-size: 15px; font-weight: 600; margin: 0 0 4px;">{DEALERSHIP_NAME}</p>
                <p style="font-size: 14px; color: #555; margin: 0 0 12px;">{DEALERSHIP_ADDRESS}</p>
                <p style="font-size: 14px; color: #555; margin: 0 0 12px;">
                    <strong>Parking:</strong> Underground parking available on-site. EV charging stations at the entrance.<br>
                    <strong>Metro:</strong> Line 1 — Argentine (3 min walk) · Line 2 — Charles de Gaulle–Étoile (5 min walk)<br>
                    <strong>Phone:</strong> {DEALERSHIP_PHONE}
                </p>
                <a href="{DEALERSHIP_MAPS}" style="display: inline-block; background: #0a0a0a; color: #fff; text-decoration: none; padding: 10px 18px; border-radius: 5px; font-size: 13px; font-weight: 600;">
                    Open in Google Maps →
                </a>
            </div>

            <p style="font-size: 13px; color: #888; margin: 0;">
                Need to reschedule? Call us at {DEALERSHIP_PHONE} and we'll sort it out.<br>
                This confirmation was sent by OttO, the EV Land voice assistant.
            </p>
        </div>
    </div>
    """
    _send_email(customer_email, subject, html)


# ---------------------------------------------------------------------------
# Main orchestrator — called from session.py after book_slot succeeds
# ---------------------------------------------------------------------------

async def handle_booking_emails(
    transcript: list[str],
    booking: dict,
    customer_email: str,
) -> None:
    """
    Generate the advisor briefing and send both emails.
    Runs after a successful book_slot() tool call.
    """
    log.info(f"Email agent triggered for booking: {booking.get('slot_datetime')} / {booking.get('customer_name')}")

    try:
        briefing = generate_advisor_briefing(transcript, booking)
        log.info("Advisor briefing generated.")
    except Exception as e:
        log.error(f"Briefing generation failed: {e}")
        briefing = "No summary available — please refer to the booking details above."

    send_advisor_email(booking, briefing)
    send_customer_email(booking, customer_email)
