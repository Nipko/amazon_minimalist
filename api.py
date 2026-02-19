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
from typing import Optional, List

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

    # Block the dates
    block_result = block_dates.add_block(booking.apt, booking.check_in, booking.check_out)

    # Build booking confirmation data
    apt_name = details.get(booking.apt, {}).get("name", booking.apt)
    apt_address = details.get(booking.apt, {}).get("location", {}).get("address", "")

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
        },
        "block_created": block_result.get("status") == "success",
        "emails_to_notify": [
            "nirlevin89@gmail.com",
            "sofia.henao96@gmail.com"
        ],
        "payment_methods": details.get(booking.apt, {}).get("payment_methods", {}),
        "message": f"Reserva confirmada para {apt_name}. Fechas bloqueadas exitosamente."
    }

    return confirmation


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
