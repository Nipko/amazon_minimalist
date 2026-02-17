"""
Amazon Minimalist — Availability Checker REST API
Deploy with: uvicorn api:app --host 0.0.0.0 --port 8000
"""

import os
from fastapi import FastAPI, HTTPException, Security, Query, Request
from fastapi.security import APIKeyHeader
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

# Import existing modules
import avail_checker
import block_dates

# --- Configuration ---
API_KEY = os.environ.get("API_KEY", "dev-key-change-me")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- App ---
app = FastAPI(
    title="Availability Checker API",
    description="API para consultar disponibilidad de apartamentos desde calendarios ICS (Airbnb/Booking.com). Diseñada para integrarse con n8n y WhatsApp.",
    version="1.0.0",
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


# --- Models ---
class BlockRequest(BaseModel):
    apt: str
    start: str  # YYYY-MM-DD
    end: str    # YYYY-MM-DD


class BlockDeleteRequest(BaseModel):
    apt: str
    start: str  # YYYY-MM-DD


# --- Endpoints ---

@app.get("/health")
async def health_check():
    """Health check endpoint. No authentication required."""
    return {"status": "ok", "service": "availability-checker"}


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
    api_key: str = Security(verify_api_key),
):
    """
    Check apartment availability for a date range.

    Fetches calendars from Airbnb and Booking.com, checks for conflicts
    with existing bookings and manual blocks.

    **n8n usage**: Use an HTTP Request node with:
    - Method: GET
    - URL: https://your-domain.com/availability?apt=amazon_minimalist&start=2026-03-01&end=2026-03-05
    - Header: X-API-Key = your-key
    """
    config = avail_checker.load_config()

    if apt not in config:
        raise HTTPException(status_code=404, detail=f"Apartment '{apt}' not found. Available: {list(config.keys())}")

    result = avail_checker.check_apartment_availability(apt, start, end, config)

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@app.post("/blocks")
async def add_block(
    block: BlockRequest,
    api_key: str = Security(verify_api_key),
):
    """
    Add a manual date block for an apartment.

    This creates a blocked period that will show as unavailable.
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


@app.get("/public/{filename}")
async def serve_ics_file(filename: str):
    """
    Serve generated ICS files (public calendar feeds).
    No authentication required so Airbnb/Booking can fetch them.
    """
    filepath = os.path.join(BASE_DIR, "public", filename)

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
