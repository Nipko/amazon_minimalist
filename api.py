"""
Amazon Minimalist — Availability Checker REST API
Deploy with: uvicorn api:app --host 0.0.0.0 --port 8000
"""

import os
import json
import mimetypes
from fastapi import FastAPI, HTTPException, Security, Query, Request
from fastapi.security import APIKeyHeader
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import asyncio
import httpx
import time
import asyncpg

# Import existing modules
import avail_checker
import block_dates

# --- Configuration ---
API_KEY = os.environ.get("API_KEY", "dev-key-change-me")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DETAILS_FILE = os.path.join(DATA_DIR, "apartments_details.json")
MEDIA_DIR = os.path.join(BASE_DIR, "multimedia")

# --- App ---
app = FastAPI(
    title="Availability Checker API",
    description="API para consultar disponibilidad de apartamentos desde calendarios ICS (Airbnb/Booking.com). Diseñada para integrarse con n8n y WhatsApp.",
    version="2.0.0",
)

# CORS — allow n8n and other services to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Webhook Proxy Config ---
N8N_WEBHOOK_URL = os.environ.get("N8N_WEBHOOK_URL", "https://n8n.parallext.cloud/webhook/1eff1133-3ba0-45cc-9ece-5f88d13c74d8")
DEBOUNCE_WAIT_SECONDS = 4.0

# Store pending messages by conversation_id: { conversation_id: {"timer": task, "payload": original_payload, "messages": [text1, text2]} }
pending_webhooks: Dict[int, Any] = {}

# --- Database Config ---
DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "postgres")
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_NAME = os.environ.get("DB_NAME", "postgres")

# Global pool
db_pool = None

# --- SMTP Config ---
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")

# --- Chatwoot Config ---
CHATWOOT_API_URL = os.environ.get("CHATWOOT_API_URL", "https://chatwoot.parallext.cloud")
CHATWOOT_API_TOKEN = os.environ.get("CHATWOOT_API_TOKEN", "")
CHATWOOT_ACCOUNT_ID = os.environ.get("CHATWOOT_ACCOUNT_ID", "1")

@app.on_event("startup")
async def startup():
    global db_pool
    try:
        db_pool = await asyncpg.create_pool(
            user=DB_USER, password=DB_PASSWORD, database=DB_NAME, host=DB_HOST, port=DB_PORT
        )
        print("Connected to PostgreSQL database.")
    except Exception as e:
        print(f"Warning: Could not connect to database at startup: {e}")

@app.on_event("shutdown")
async def shutdown():
    global db_pool
    if db_pool:
        await db_pool.close()

# --- Security ---
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Security(api_key_header)):
    if api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing API Key")
    return api_key


# --- Helpers ---
def load_details():
    """Load the full apartment details JSON."""
    try:
        with open(DETAILS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def get_media_url(request: Request, apt_id: str, filename: str) -> str:
    """Build a full media URL for a photo/video."""
    base = str(request.base_url).rstrip("/")
    return f"{base}/media/{apt_id}/{filename}"

def send_confirmation_email(booking, apt_name, apt_address):
    """Sends a confirmation email to the guest using SMTP."""
    if not SMTP_USER or not SMTP_PASSWORD or not booking.guest_email:
        print("Skipping email: Missing SMTP credentials or guest email.")
        return False

    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    msg = MIMEMultipart()
    msg['From'] = SMTP_USER
    msg['To'] = booking.guest_email
    msg['Subject'] = f"Confirmación de Reserva en {apt_name}"

    html = f"""
    <html>
      <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
        <h2 style="color: #2c3e50;">¡Hola {booking.guest_name}!</h2>
        <p>Tu reserva en <strong>{apt_name}</strong> ha sido confirmada con éxito. Nos hace muy felices recibirte en Leticia, Amazonas.</p>
        
        <h3 style="border-bottom: 1px solid #eee; padding-bottom: 5px;">Detalles de la Reserva:</h3>
        <ul>
          <li><strong>Lugar:</strong> {apt_name}</li>
          <li><strong>Dirección:</strong> {apt_address}</li>
          <li><strong>Check-in:</strong> {booking.check_in} (3:00 PM)</li>
          <li><strong>Check-out:</strong> {booking.check_out} (11:00 AM)</li>
          <li><strong>Huéspedes:</strong> {booking.num_guests} personas</li>
          <li><strong>Precio Total:</strong> {booking.total_price} COP</li>
        </ul>
        
        <p>{"<strong>Notas adicionales:</strong> " + booking.notes if booking.notes else ""}</p>
        
        <p>Por favor conserva este correo como copia de tu confirmación. Si tienes alguna duda, puedes respondernos a nuestro WhatsApp.</p>
        <br>
        <p>¡Te esperamos pronto!</p>
        <p><strong>El equipo de Amazon Minimalist</strong></p>
      </body>
    </html>
    """
    
    msg.attach(MIMEText(html, 'html'))

    try:
        # Use SMTP_SSL if port is 465, or starttls if port is 587
        if SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        else:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            server.starttls()
            
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(f"Confirmation email successfully sent to {booking.guest_email}")
        return True
    except Exception as e:
        print(f"Failed to send email to {booking.guest_email}: {e}")
        return False


# --- Models ---
class BlockRequest(BaseModel):
    apt: str
    start: str  # YYYY-MM-DD
    end: str    # YYYY-MM-DD


class BlockDeleteRequest(BaseModel):
    apt: str
    start: str  # YYYY-MM-DD


class QueryRequest(BaseModel):
    apartment_id: Optional[str] = None
    check_in: Optional[str] = None
    check_out: Optional[str] = None
    num_guests: Optional[int] = None
    question_type: str = "all"  # availability | details | prices | photos | all
    include_photos: bool = True
    include_videos: bool = False  # Solo enviar videos si se solicita explícitamente


# --- Endpoints ---

@app.get("/health")
async def health_check():
    """Health check endpoint. No authentication required."""
    return {"status": "ok", "service": "availability-checker", "version": "2.0.0"}


@app.get("/apartments")
async def list_apartments(api_key: str = Security(verify_api_key)):
    """List all configured apartments and their names."""
    config = avail_checker.load_config()
    apartments = []
    for apt_id, apt_data in config.items():
        apartments.append({
            "id": apt_id,
            "name": apt_data["name"],
            "sources_count": len(apt_data.get("sources", []))
        })
    return {"apartments": apartments}


@app.get("/availability")
async def check_availability(
    apt: str = Query(..., description="Apartment ID (e.g. amazon_minimalist)"),
    start: str = Query(..., description="Check-in date (YYYY-MM-DD)"),
    end: str = Query(..., description="Check-out date (YYYY-MM-DD)"),
    num_guests: Optional[int] = Query(None, description="Number of guests (optional, for price calculation)"),
    api_key: str = Security(verify_api_key),
):
    """
    Check apartment availability for a date range.

    Fetches calendars from Airbnb and Booking.com, checks for conflicts
    with existing bookings and manual blocks.
    If num_guests is provided and dates are available, also returns pricing.
    """
    config = avail_checker.load_config()

    if apt not in config:
        raise HTTPException(status_code=404, detail=f"Apartment '{apt}' not found. Available: {list(config.keys())}")

    result = avail_checker.check_apartment_availability(apt, start, end, config)

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    # Add pricing if available and num_guests provided
    if result.get("available") and num_guests is not None:
        import datetime as dt
        details = load_details()
        apt_data = details.get(apt, {})
        pricing = apt_data.get("pricing", {})
        discount_map = pricing.get("discount_by_guests", {})
        base_price = pricing.get("base_price_per_night", 0)

        # Calculate price per night based on guests
        if apt == "amazon_minimalist":
            if num_guests >= 3:
                price_per_night = discount_map.get("3_guests", base_price)
            elif num_guests == 2:
                price_per_night = discount_map.get("2_guests", base_price)
            else:
                price_per_night = discount_map.get("1_guest", base_price)
        elif apt == "family_amazon_minimalist":
            if num_guests >= 5:
                price_per_night = discount_map.get("5_6_guests", base_price)
            elif num_guests >= 3:
                price_per_night = discount_map.get("3_4_guests", base_price)
            else:
                price_per_night = discount_map.get("1_2_guests", base_price)
        else:
            price_per_night = base_price

        # Calculate number of nights
        try:
            d_start = dt.datetime.strptime(start, "%Y-%m-%d").date()
            d_end = dt.datetime.strptime(end, "%Y-%m-%d").date()
            num_nights = (d_end - d_start).days
        except ValueError:
            num_nights = 0

        result["pricing"] = {
            "price_per_night": price_per_night,
            "num_nights": num_nights,
            "total_price": price_per_night * num_nights,
            "currency": "COP",
            "num_guests": num_guests,
            "discount_by_stay": pricing.get("discount_by_stay", {}),
            "deposit_policy": pricing.get("deposit_policy", ""),
        }

    return result


# --- Photos Endpoint (lightweight, for n8n direct call) ---

@app.get("/apartments/{apt_id}/photos")
async def get_apartment_photos(
    apt_id: str,
    request: Request,
):
    """
    Lightweight endpoint: returns only photo and video URLs.
    No authentication required — called by n8n directly, not by the LLM.
    Photos are already public via /media/ endpoint.
    """
    details = load_details()

    if apt_id not in details or apt_id in ("legal", "cross_apartment_policy"):
        available = [k for k in details.keys() if k not in ("legal", "cross_apartment_policy")]
        raise HTTPException(status_code=404, detail=f"Apartment '{apt_id}' not found. Available: {available}")

    apt_data = details[apt_id]
    return {
        "apartment": apt_id,
        "name": apt_data.get("name", ""),
        "photos": [get_media_url(request, apt_id, p) for p in apt_data.get("photos", [])],
        "videos": [get_media_url(request, apt_id, v) for v in apt_data.get("videos", [])],
    }


# --- Details Endpoints ---

@app.get("/details")
async def get_all_details(
    request: Request,
    api_key: str = Security(verify_api_key),
):
    """Get full details for all apartments including prices, amenities, rules, and media URLs."""
    details = load_details()
    result = {}

    for apt_id, apt_data in details.items():
        if apt_id in ("legal", "cross_apartment_policy"):
            result[apt_id] = apt_data
            continue
        
        apt_copy = dict(apt_data)
        # Add full photo URLs
        if "photos" in apt_copy:
            apt_copy["photo_urls"] = [get_media_url(request, apt_id, p) for p in apt_copy["photos"]]
        if "videos" in apt_copy:
            apt_copy["video_urls"] = [get_media_url(request, apt_id, v) for v in apt_copy["videos"]]
        result[apt_id] = apt_copy

    return result


@app.get("/details/{apt_id}")
async def get_apartment_details(
    apt_id: str,
    request: Request,
    api_key: str = Security(verify_api_key),
):
    """Get full details for a specific apartment."""
    details = load_details()

    if apt_id not in details:
        available = [k for k in details.keys() if k not in ("legal", "cross_apartment_policy")]
        raise HTTPException(status_code=404, detail=f"Apartment '{apt_id}' not found. Available: {available}")

    apt_data = dict(details[apt_id])
    # Add full photo URLs
    if "photos" in apt_data:
        apt_data["photo_urls"] = [get_media_url(request, apt_id, p) for p in apt_data["photos"]]
    if "videos" in apt_data:
        apt_data["video_urls"] = [get_media_url(request, apt_id, v) for v in apt_data["videos"]]

    # Include legal and cross-apartment policy
    apt_data["legal"] = details.get("legal", {})
    apt_data["cross_apartment_policy"] = details.get("cross_apartment_policy", "")

    return apt_data


# --- Query Endpoint (main endpoint for n8n AI Agent) ---

@app.post("/query")
async def query_apartment(
    query: QueryRequest,
    request: Request,
    api_key: str = Security(verify_api_key),
):
    """
    Main query endpoint for n8n AI Agent integration.

    Receives a structured query and returns relevant apartment info.
    If data is missing (e.g. no dates for availability check), returns 
    'missing_info' so the agent can ask the user.

    **question_type options**: availability, details, prices, photos, all
    """
    details = load_details()
    config = avail_checker.load_config()
    response = {}
    missing_info = []

    # Determine which apartment(s) to query
    apt_ids = []
    if query.apartment_id:
        if query.apartment_id not in details or query.apartment_id in ("legal", "cross_apartment_policy"):
            available = [k for k in details.keys() if k not in ("legal", "cross_apartment_policy")]
            raise HTTPException(status_code=404, detail=f"Apartment '{query.apartment_id}' not found. Available: {available}")
        apt_ids = [query.apartment_id]
    else:
        apt_ids = [k for k in details.keys() if k not in ("legal", "cross_apartment_policy")]

    apartments_response = {}

    for apt_id in apt_ids:
        apt_info = {}
        apt_data = details.get(apt_id, {})

        # --- Details ---
        if query.question_type in ("details", "all"):
            apt_info["name"] = apt_data.get("name", "")
            apt_info["description"] = apt_data.get("description", "")
            apt_info["location"] = apt_data.get("location", {})
            apt_info["capacity"] = apt_data.get("capacity", {})
            apt_info["amenities"] = apt_data.get("amenities", [])
            apt_info["check_in_time"] = apt_data.get("check_in_time", "")
            apt_info["check_out_time"] = apt_data.get("check_out_time", "")
            apt_info["rules"] = apt_data.get("rules", [])
            apt_info["luggage_storage"] = apt_data.get("luggage_storage", "")
            apt_info["hot_water"] = apt_data.get("hot_water", True if "Agua caliente" in str(apt_data.get("amenities", [])) else False)
            apt_info["rnt"] = apt_data.get("rnt", "")
            apt_info["social_media"] = apt_data.get("social_media", {})

        # --- Prices ---
        if query.question_type in ("prices", "all"):
            pricing = dict(apt_data.get("pricing", {}))
            
            # Calculate price based on number of guests if provided
            if query.num_guests:
                discount_map = pricing.get("discount_by_guests", {})
                applicable_price = pricing.get("base_price_per_night")
                
                if apt_id == "amazon_minimalist":
                    if query.num_guests >= 3:
                        applicable_price = discount_map.get("3_guests", applicable_price)
                    elif query.num_guests == 2:
                        applicable_price = discount_map.get("2_guests", applicable_price)
                    else:
                        applicable_price = discount_map.get("1_guest", applicable_price)
                elif apt_id == "family_amazon_minimalist":
                    if query.num_guests >= 5:
                        applicable_price = discount_map.get("5_6_guests", applicable_price)
                    elif query.num_guests >= 3:
                        applicable_price = discount_map.get("3_4_guests", applicable_price)
                    else:
                        applicable_price = discount_map.get("1_2_guests", applicable_price)
                
                pricing["calculated_price_per_night"] = applicable_price
                pricing["for_guests"] = query.num_guests

            apt_info["pricing"] = pricing
            apt_info["payment_methods"] = apt_data.get("payment_methods", {})

        # --- Availability ---
        if query.question_type in ("availability", "all"):
            if query.check_in and query.check_out:
                if apt_id in config:
                    avail_result = avail_checker.check_apartment_availability(
                        apt_id, query.check_in, query.check_out, config
                    )
                    apt_info["availability"] = avail_result
                else:
                    apt_info["availability"] = {"error": f"No calendar sources for {apt_id}"}
            else:
                if not query.check_in:
                    missing_info.append("check_in")
                if not query.check_out:
                    missing_info.append("check_out")

        # --- Photos ---
        if query.question_type in ("photos", "all") and query.include_photos:
            photos = apt_data.get("photos", [])
            apt_info["photo_urls"] = [get_media_url(request, apt_id, p) for p in photos]

        # --- Videos (only if explicitly requested) ---
        if query.include_videos:
            videos = apt_data.get("videos", [])
            apt_info["video_urls"] = [get_media_url(request, apt_id, v) for v in videos]

        apartments_response[apt_id] = apt_info

    response["apartments"] = apartments_response

    # Add missing info for the agent to ask
    if missing_info:
        response["missing_info"] = list(set(missing_info))
        response["missing_message"] = "Para consultar la disponibilidad necesito las fechas de check-in y check-out."

    # Add legal info and cross-apartment policy
    if query.question_type in ("details", "all"):
        response["legal"] = details.get("legal", {})
        response["cross_apartment_policy"] = details.get("cross_apartment_policy", "")

    return response


# --- Media Endpoint ---

@app.get("/media/{apt_id}/{filename}")
async def serve_media(apt_id: str, filename: str):
    """
    Serve apartment photos and videos.
    No authentication required so WhatsApp can fetch the media URLs.
    """
    # Map apt_id to folder names
    folder_map = {
        "amazon_minimalist": "Amazon_minimalist",
        "family_amazon_minimalist": "Family_Amazon_minimalist",
    }

    folder = folder_map.get(apt_id)
    if not folder:
        raise HTTPException(status_code=404, detail=f"Unknown apartment: {apt_id}")

    filepath = os.path.join(MEDIA_DIR, folder, filename)

    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    # Detect content type
    content_type, _ = mimetypes.guess_type(filepath)
    if content_type is None:
        content_type = "application/octet-stream"

    return FileResponse(
        filepath,
        media_type=content_type,
        filename=filename,
    )


# --- Booking Confirmation ---

class BookingRequest(BaseModel):
    apt: str
    guest_name: str
    guest_phone: str = ""
    guest_email: str = ""
    check_in: str   # YYYY-MM-DD
    check_out: str  # YYYY-MM-DD
    num_guests: int
    price_per_night: int
    total_price: int
    notes: str = ""


@app.post("/bookings")
async def confirm_booking(
    booking: BookingRequest,
    api_key: str = Security(verify_api_key),
):
    """
    Confirm a booking: blocks the dates and returns booking data for email.
    This endpoint is called by the n8n AI Agent when a guest confirms.
    """
    config = avail_checker.load_config()
    details = load_details()

    if booking.apt not in config:
        raise HTTPException(status_code=404, detail=f"Apartment '{booking.apt}' not found")

    # First verify availability
    avail_result = avail_checker.check_apartment_availability(
        booking.apt, booking.check_in, booking.check_out, config
    )
    if not avail_result.get("available", False):
        raise HTTPException(
            status_code=409,
            detail="Las fechas solicitadas ya no están disponibles. Conflicto con reservas existentes."
        )

    # Bloquear las fechas en el calendario
    block_result = block_dates.add_block(booking.apt, booking.check_in, booking.check_out)

    # Registrar reserva en PostgreSQL
    global db_pool
    db_success = False
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                # 1. Asegurar que el contacto existe
                if booking.guest_phone:
                    await conn.execute(
                        """
                        INSERT INTO conversaciones (telefono, nombre_contacto, es_nombre_valido)
                        VALUES ($1, $2, TRUE)
                        ON CONFLICT (telefono) DO UPDATE SET nombre_contacto = $2, es_nombre_valido = TRUE
                        """,
                        booking.guest_phone, booking.guest_name
                    )

                    # 2. Insertar reserva
                    import datetime
                    d_in = datetime.datetime.strptime(booking.check_in, "%Y-%m-%d").date()
                    d_out = datetime.datetime.strptime(booking.check_out, "%Y-%m-%d").date()

                    await conn.execute(
                        """
                        INSERT INTO reservas (fk_telefono, apartamento_id, nombre_reserva, check_in, check_out, num_huespedes, precio_total)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        """,
                        booking.guest_phone, booking.apt, booking.guest_name, d_in, d_out, booking.num_guests, float(booking.total_price)
                    )
                    db_success = True
        except Exception as e:
            print(f"Error saving to database: {e}")

    # Build booking confirmation data
    apt_name = details.get(booking.apt, {}).get("name", booking.apt)
    apt_address = details.get(booking.apt, {}).get("location", {}).get("address", "")
    
    # Send confirmation email
    email_sent = False
    if booking.guest_email:
        email_sent = send_confirmation_email(booking, apt_name, apt_address)

    confirmation = {
        "status": "confirmed",
        "booking": {
            "apartment_name": apt_name,
            "apartment_id": booking.apt,
            "address": apt_address,
            "guest_name": booking.guest_name,
            "guest_phone": booking.guest_phone,
            "guest_email": booking.guest_email,
            "check_in": booking.check_in,
            "check_out": booking.check_out,
            "check_in_time": "3:00 PM",
            "check_out_time": "11:00 AM",
            "num_guests": booking.num_guests,
            "price_per_night": booking.price_per_night,
            "total_price": booking.total_price,
            "currency": "COP",
            "notes": booking.notes,
            "db_saved": db_success,
            "email_sent": email_sent
        },
        "block_created": block_result.get("status") == "success",
        "emails_to_notify": [
            "nirlevin89@gmail.com",
            "sofia.henao96@gmail.com"
        ],
        "payment_methods": details.get(booking.apt, {}).get("payment_methods", {}),
        "message": f"Reserva confirmada para {apt_name}. Fechas bloqueadas exitosamente. Correo enviado: {'Sí' if email_sent else 'No'}"
    }

    return confirmation


@app.get("/bookings/contact/{phone}")
async def get_booking_history(
    phone: str,
    api_key: str = Security(verify_api_key),
):
    """
    Get booking history and last conversation summary for a specific phone number.
    Used by the AI Agent to remember previous interactions and validate context.
    """
    global db_pool
    if not db_pool:
        # En caso de no tener DB, retornar vacío temporalmente
        return {"phone": phone, "history": [], "last_summary": ""}

    # Remover el '+' posible para normalizar, aunque asuma formato uniforme
    clean_phone = phone.replace(" ", "").strip()

    history = []
    summary = ""
    es_nombre_valido = False
    nombre_contacto = ""

    try:
        async with db_pool.acquire() as conn:
            # Info del contacto
            row_contact = await conn.fetchrow(
                "SELECT nombre_contacto, ultimo_resumen, es_nombre_valido FROM conversaciones WHERE telefono = $1", 
                clean_phone
            )
            if row_contact:
                nombre_contacto = row_contact["nombre_contacto"]
                summary = row_contact["ultimo_resumen"] or ""
                es_nombre_valido = row_contact["es_nombre_valido"]

            # Reservas previas
            rows_reservas = await conn.fetch(
                """
                SELECT apartamento_id, check_in, check_out, num_huespedes, precio_total, creado_en 
                FROM reservas 
                WHERE fk_telefono = $1 
                ORDER BY check_in DESC
                """, 
                clean_phone
            )
            for r in rows_reservas:
                history.append({
                    "apartment_id": r["apartamento_id"],
                    "check_in": r["check_in"].isoformat(),
                    "check_out": r["check_out"].isoformat(),
                    "num_guests": r["num_huespedes"],
                    "total_price": float(r["precio_total"]),
                    "booked_at": r["creado_en"].isoformat() if r["creado_en"] else None
                })

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")

    return {
        "phone": clean_phone,
        "name": nombre_contacto,
        "valid_name": es_nombre_valido,
        "last_summary": summary,
        "past_bookings": history,
        "has_history": len(history) > 0
    }

class SummaryRequest(BaseModel):
    phone: str
    name: str = ""
    summary: str

@app.post("/conversations/summary")
async def save_conversation_summary(
    data: SummaryRequest,
    api_key: str = Security(verify_api_key),
):
    """
    Guarda el resumen de la última conversación de un usuario en la tabla `conversaciones`.
    """
    global db_pool
    if not db_pool:
         return {"error": "Database not configured"}
    
    clean_phone = data.phone.replace(" ", "").strip()
    
    try:
         async with db_pool.acquire() as conn:
             await conn.execute(
                 """
                 INSERT INTO conversaciones (telefono, nombre_contacto, ultimo_resumen, fecha_ultimo_mensaje)
                 VALUES ($1, $2, $3, CURRENT_TIMESTAMP)
                 ON CONFLICT (telefono) DO UPDATE 
                 SET ultimo_resumen = $3, fecha_ultimo_mensaje = CURRENT_TIMESTAMP,
                     nombre_contacto = COALESCE(NULLIF($2, ''), conversaciones.nombre_contacto)
                 """,
                 clean_phone, data.name, data.summary
             )
    except Exception as e:
         raise HTTPException(status_code=500, detail=f"Database error: {e}")
         
    return {"status": "success", "message": "Resumen guardado correctamente."}


# --- Block Endpoints ---

@app.post("/blocks")
async def add_block(
    block: BlockRequest,
    api_key: str = Security(verify_api_key),
):
    """
    Add a manual date block for an apartment.
    Also regenerates the ICS file for the apartment.
    """
    result = block_dates.add_block(block.apt, block.start, block.end)

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@app.delete("/blocks")
async def delete_block(
    block: BlockDeleteRequest,
    api_key: str = Security(verify_api_key),
):
    """
    Remove a manual date block by its start date.
    Also regenerates the ICS file for the apartment.
    """
    result = block_dates.remove_block(block.apt, block.start)

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@app.get("/blocks/{apt_id}")
async def get_blocks(
    apt_id: str,
    api_key: str = Security(verify_api_key),
):
    """List all manual blocks for a specific apartment."""
    config = avail_checker.load_config()

    if apt_id not in config:
        raise HTTPException(status_code=404, detail=f"Apartment '{apt_id}' not found")

    blocks = block_dates.list_blocks(apt_id)
    return {"apartment": apt_id, "blocks": blocks, "count": len(blocks)}


# --- ICS Files ---

@app.get("/public/{filename}")
async def serve_ics_file(filename: str):
    """
    Serve generated ICS files (public calendar feeds).
    No authentication required so Airbnb/Booking can fetch them.
    """
    filepath = os.path.join(BASE_DIR, "data", "public", filename)

    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        filepath,
        media_type="text/calendar",
        filename=filename,
    )


# --- Error Handler ---
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)},
    )


# --- Webhook Debounce Proxy ---

async def send_to_n8n(conversation_id: int):
    """Wait for debounce period, consolidate messages, and send to n8n."""
    await asyncio.sleep(DEBOUNCE_WAIT_SECONDS)
    
    # After sleep, execute the webhook
    data = pending_webhooks.pop(conversation_id, None)
    if not data:
        return

    payload = data["payload"]
    messages = data["messages"]
    
    # Consolidate messages by joining them with newlines
    consolidated_text = "\n".join(messages)
    
    # Overwrite the payload content with the consolidated text
    try:
        payload["content"] = consolidated_text
        if "conversation" in payload and "messages" in payload["conversation"] and len(payload["conversation"]["messages"]) > 0:
            payload["conversation"]["messages"][0]["content"] = consolidated_text
            payload["conversation"]["messages"][0]["processed_message_content"] = consolidated_text
    except Exception as e:
        print(f"Error consolidating payload: {e}")

    # Forward to n8n
    print(f"Forwarding {len(messages)} messages to n8n for conversation {conversation_id}:\n{consolidated_text}")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(N8N_WEBHOOK_URL, json=payload)
            print(f"n8n response: {resp.status_code}")
    except Exception as e:
        print(f"Error sending to n8n: {e}")

async def auto_register_contact(payload: dict):
    """Auto-register contact in PostgreSQL from incoming webhook payload."""
    global db_pool
    if not db_pool:
        return
    try:
        sender = payload.get("sender", {}) or payload.get("conversation", {}).get("meta", {}).get("sender", {})
        phone = sender.get("phone_number", "").replace(" ", "").strip()
        name = sender.get("name", "").strip()
        if not phone:
            return
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO conversaciones (telefono, nombre_contacto, fecha_ultimo_mensaje)
                VALUES ($1, $2, CURRENT_TIMESTAMP)
                ON CONFLICT (telefono) DO UPDATE
                SET fecha_ultimo_mensaje = CURRENT_TIMESTAMP,
                    nombre_contacto = COALESCE(NULLIF($2, ''), conversaciones.nombre_contacto)
                """,
                phone, name
            )
        print(f"Auto-registered contact: {phone} ({name})")
    except Exception as e:
        print(f"Error auto-registering contact: {e}")


async def apply_chatwoot_label(conversation_id: int, labels: list):
    """Apply labels to a Chatwoot conversation via their API."""
    if not CHATWOOT_API_TOKEN:
        print("Skipping label: No Chatwoot API token configured.")
        return False
    url = f"{CHATWOOT_API_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}/conversations/{conversation_id}/labels"
    headers = {
        "Content-Type": "application/json",
        "api_access_token": CHATWOOT_API_TOKEN
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json={"labels": labels}, headers=headers)
            print(f"Chatwoot label response ({conversation_id}): {resp.status_code} - {labels}")
            return resp.status_code == 200
    except Exception as e:
        print(f"Error applying Chatwoot label: {e}")
        return False


async def auto_label_new_contact(conversation_id: int, payload: dict):
    """Auto-label conversation as 'nuevo' or 'repetido' based on DB history."""
    global db_pool
    if not db_pool or not CHATWOOT_API_TOKEN:
        return
    try:
        sender = payload.get("sender", {}) or payload.get("conversation", {}).get("meta", {}).get("sender", {})
        phone = sender.get("phone_number", "").replace(" ", "").strip()
        if not phone:
            return
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) as cnt FROM reservas WHERE fk_telefono = $1", phone
            )
            has_history = row and row["cnt"] > 0
        label = "repetido" if has_history else "nuevo"
        await apply_chatwoot_label(conversation_id, [label])
    except Exception as e:
        print(f"Error auto-labeling contact: {e}")


class LabelRequest(BaseModel):
    conversation_id: int
    labels: List[str]

@app.post("/conversations/label")
async def label_conversation(
    data: LabelRequest,
    api_key: str = Security(verify_api_key),
):
    """Apply labels to a Chatwoot conversation. Called by n8n after agent processing."""
    success = await apply_chatwoot_label(data.conversation_id, data.labels)
    if not success:
        raise HTTPException(status_code=502, detail="Failed to apply labels in Chatwoot")
    return {"status": "success", "conversation_id": data.conversation_id, "labels": data.labels}


@app.post("/webhook/chatwoot")
async def chatwoot_webhook(request: Request):
    """
    Proxy to receive webhooks from Chatwoot, group them by conversation within
    a short time window (debounce), and forward a single consolidated message to n8n.
    """
    try:
        payload = await request.json()
    except Exception:
        return {"status": "error", "message": "Invalid JSON"}

    # We only debounce incoming message_created events
    if payload.get("event") != "message_created" or payload.get("message_type") != "incoming":
        # Forward immediately without debouncing
        asyncio.create_task(forward_immediately(payload))
        return {"status": "ok", "forwarded_async": True}

    # Auto-register contact on every incoming message
    asyncio.create_task(auto_register_contact(payload))

    conversation = payload.get("conversation", {})
    conversation_id = conversation.get("id")
    
    content = payload.get("content", "").strip()

    if not conversation_id or not content:
        # Invalid payload or no text, forward immediately
        asyncio.create_task(forward_immediately(payload))
        return {"status": "ok", "forwarded_async": True}

    # Auto-label as 'nuevo' if first time (fire and forget)
    asyncio.create_task(auto_label_new_contact(conversation_id, payload))

    # Debounce logic
    global pending_webhooks
    
    if conversation_id in pending_webhooks:
        pending_webhooks[conversation_id]["timer"].cancel()
        pending_webhooks[conversation_id]["messages"].append(content)
        new_task = asyncio.create_task(send_to_n8n(conversation_id))
        pending_webhooks[conversation_id]["timer"] = new_task
    else:
        new_task = asyncio.create_task(send_to_n8n(conversation_id))
        pending_webhooks[conversation_id] = {
            "timer": new_task,
            "payload": payload,
            "messages": [content]
        }
        
    return {"status": "ok", "message": "debounced"}


async def forward_immediately(payload: dict):
    """Forward a non-debounced webhook immediately to n8n."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            await client.post(N8N_WEBHOOK_URL, json=payload)
    except Exception as e:
        print(f"Error forwarding unhandled webhook to n8n: {e}")
