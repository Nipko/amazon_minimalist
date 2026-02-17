import json
import argparse
import sys
import os
import datetime
import requests
import threading
from icalendar import Calendar
from dateutil.rrule import rrulestr

# --- Configuration ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
CONFIG_FILE = os.path.join(DATA_DIR, 'apartments.json')

def load_config():
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(json.dumps({"error": f"Config file {CONFIG_FILE} not found", "available": False}))
        sys.exit(1)

# --- Core Logic ---

def fetch_ics(url):
    """Downloads ICS content from a URL."""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.text
    except Exception as e:
        # We log to stderr to avoid polluting the JSON stdout
        sys.stderr.write(f"Error fetching {url}: {e}\n")
        return None

def parse_ics(ics_content):
    """Parses ICS content and returns a list of occupied date ranges."""
    occupied_ranges = []
    if not ics_content:
        return occupied_ranges

    try:
        cal = Calendar.from_ical(ics_content)
        for component in cal.walk():
            if component.name == "VEVENT":
                start = component.get('dtstart')
                end = component.get('dtend')
                
                if start and end:
                    # Normalized to date objects (ignore time for whole-day bookings)
                    s_date = start.dt
                    e_date = end.dt
                    
                    if isinstance(s_date, datetime.datetime):
                        s_date = s_date.date()
                    if isinstance(e_date, datetime.datetime):
                        e_date = e_date.date()
                        
                    # Calculate duration for single day events if needed, 
                    # but typically ICS end date is exclusive. 
                    # Booking/Airbnb usually send checkout day as end date.
                    
                    occupied_ranges.append((s_date, e_date))
    except Exception as e:
        sys.stderr.write(f"Error parsing ICS: {e}\n")

    return occupied_ranges

def is_date_range_available(occupied_ranges, check_in, check_out):
    """
    Checks if the requested [check_in, check_out) range overlaps with any occupied range.
    Note: check_out is exclusive in logic (you leave that morning), 
    so overlap occurs if (RequestStart < ExistingEnd) and (RequestEnd > ExistingStart).
    """
    conflicts = []
    for start, end in occupied_ranges:
        # Standard overlap check:
        # Request:   |------|
        # Existing:      |------|
        if check_in < end and check_out > start:
            conflicts.append(f"{start} to {end}")
            
    return len(conflicts) == 0, conflicts

def check_apartment_availability(apt_id, check_in_str, check_out_str, config):
    if apt_id not in config:
        return {"error": "Apartment ID not found", "available": False}

    try:
        check_in = datetime.datetime.strptime(check_in_str, "%Y-%m-%d").date()
        check_out = datetime.datetime.strptime(check_out_str, "%Y-%m-%d").date()
    except ValueError:
        return {"error": "Invalid date format. Use YYYY-MM-DD", "available": False}

    sources = config[apt_id]['sources']
    
    # Fetch all calendars in parallel
    ics_contents = []
    threads = []
    
    def fetch_worker(url):
        content = fetch_ics(url)
        if content:
            ics_contents.append(content)

    for url in sources:
        t = threading.Thread(target=fetch_worker, args=(url,))
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()

    # Parse all
    all_occupied_ranges = []
    for content in ics_contents:
        all_occupied_ranges.extend(parse_ics(content))

    # Check availability
    is_available, conflicts = is_date_range_available(all_occupied_ranges, check_in, check_out)

    return {
        "apartment": config[apt_id]['name'],
        "check_in": check_in_str,
        "check_out": check_out_str,
        "available": is_available,
        "reason": "Dates are free" if is_available else "Conflict with existing bookings",
        "conflicts": conflicts
    }

# --- CLI Entrypoint ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check apartment availability from ICS feeds.")
    parser.add_argument("--apt", required=True, help="Apartment ID (key in JSON config)")
    parser.add_argument("--start", required=True, help="Check-in date (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="Check-out date (YYYY-MM-DD)")
    
    args = parser.parse_args()
    
    config = load_config()
    result = check_apartment_availability(args.apt, args.start, args.end, config)
    
    # Output JSON to stdout
    print(json.dumps(result, indent=2))
