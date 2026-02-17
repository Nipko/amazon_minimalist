import json
import argparse
import sys
import os
import datetime
from icalendar import Calendar, Event
import uuid

# --- Configuration ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
BLOCKS_DB = os.path.join(DATA_DIR, 'blocks.json')
PUBLIC_DIR = os.path.join(DATA_DIR, 'public')
CONFIG_FILE = os.path.join(DATA_DIR, 'apartments.json')

def load_config():
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(json.dumps({"error": f"Config file {CONFIG_FILE} not found"}))
        sys.exit(1)

def load_blocks():
    if not os.path.exists(BLOCKS_DB):
        return {}
    try:
        with open(BLOCKS_DB, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

def save_blocks(blocks):
    with open(BLOCKS_DB, 'w', encoding='utf-8') as f:
        json.dump(blocks, f, indent=2)

def generate_ics(apt_id, blocks_list, apt_name):
    """Generates an ICS file for the given apartment blocks."""
    cal = Calendar()
    cal.add('prodid', f'-//My Apartment Manager//mxm.dk//')
    cal.add('version', '2.0')
    cal.add('X-WR-CALNAME', f'Bloqueos Manuales - {apt_name}')

    for block in blocks_list:
        event = Event()
        # Create a unique UID for the event if stored, otherwise generate one (stable if possible)
        # Here we generate one on fly, but better reuse if we had ID. 
        # For simplicity, we use startdate-apt as seed or just random.
        # Since we regenerate the whole file, it's safer to have stable UIDs if we want updates to verify well,
        # but for simple blocking, a fresh UID each gen is usually accepted by OTAs as "new event" replacing old if calendar is refreshed.
        # Ideally, we should store a UID in blocks.json.
        
        uid = block.get('uid', str(uuid.uuid4()))
        event.add('summary', 'Bloqueo Manual')
        
        # Parse dates
        dt_start = datetime.datetime.strptime(block['start'], '%Y-%m-%d').date()
        dt_end = datetime.datetime.strptime(block['end'], '%Y-%m-%d').date()
        
        # ICS events are exclusive of end date for full days, so we ensure 
        # input is treated correctly. If user says "Block 20 to 22", usually means 20, 21 (checkout 22).
        
        event.add('dtstart', dt_start)
        event.add('dtend', dt_end) 
        event.add('dtstamp', datetime.datetime.now())
        event.add('uid', uid)
        
        cal.add_component(event)

    # Ensure public dir exists
    if not os.path.exists(PUBLIC_DIR):
        os.makedirs(PUBLIC_DIR)
        
    filename = os.path.join(PUBLIC_DIR, f'{apt_id}_blocks.ics')
    
    with open(filename, 'wb') as f:
        f.write(cal.to_ical())
        
    return filename

# --- Standalone Functions (importable from api.py) ---

def add_block(apt_id, start_date, end_date):
    """Add a manual block for an apartment. Returns result dict."""
    config = load_config()
    if apt_id not in config:
        return {"error": "Apartment ID not found in configuration"}

    blocks_db = load_blocks()
    if apt_id not in blocks_db:
        blocks_db[apt_id] = []

    new_block = {
        "start": start_date,
        "end": end_date,
        "uid": str(uuid.uuid4()),
        "created_at": str(datetime.datetime.now())
    }
    blocks_db[apt_id].append(new_block)
    save_blocks(blocks_db)

    ics_path = generate_ics(apt_id, blocks_db[apt_id], config[apt_id]['name'])
    return {
        "status": "success",
        "message": "Block added and ICS regenerated",
        "ics_file": ics_path,
        "uid": new_block['uid'],
        "block": new_block
    }

def remove_block(apt_id, start_date):
    """Remove a block by start date. Returns result dict."""
    config = load_config()
    if apt_id not in config:
        return {"error": "Apartment ID not found in configuration"}

    blocks_db = load_blocks()
    if apt_id not in blocks_db:
        return {"status": "no_change", "message": "No blocks found for this apartment"}

    current_blocks = blocks_db[apt_id]
    initial_len = len(current_blocks)
    current_blocks = [b for b in current_blocks if b['start'] != start_date]

    if len(current_blocks) == initial_len:
        return {"status": "no_change", "message": "No block found with that start date"}

    blocks_db[apt_id] = current_blocks
    save_blocks(blocks_db)
    ics_path = generate_ics(apt_id, current_blocks, config[apt_id]['name'])
    return {"status": "success", "message": "Block removed and ICS regenerated", "ics_file": ics_path}

def list_blocks(apt_id):
    """List all blocks for an apartment. Returns list."""
    blocks_db = load_blocks()
    return blocks_db.get(apt_id, [])

def regenerate_ics_for_apt(apt_id):
    """Regenerate the ICS file for an apartment. Returns result dict."""
    config = load_config()
    if apt_id not in config:
        return {"error": "Apartment ID not found in configuration"}

    blocks_db = load_blocks()
    current_blocks = blocks_db.get(apt_id, [])
    ics_path = generate_ics(apt_id, current_blocks, config[apt_id]['name'])
    return {"status": "success", "message": "ICS regenerated", "ics_file": ics_path}


def main():
    parser = argparse.ArgumentParser(description="Manage manual date blocks and generate ICS.")
    parser.add_argument("--apt", required=True, help="Apartment ID")
    parser.add_argument("--start", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", help="End date YYYY-MM-DD")
    parser.add_argument("--action", choices=['add', 'remove', 'list', 'regenerate'], default='list', help="Action to perform")

    args = parser.parse_args()

    if args.action == 'add':
        if not args.start or not args.end:
            print(json.dumps({"error": "Start and End dates required for add"}))
            sys.exit(1)
        result = add_block(args.apt, args.start, args.end)
        print(json.dumps(result, indent=2))

    elif args.action == 'remove':
        if not args.start:
            print(json.dumps({"error": "Start date required to identify block to remove"}))
            sys.exit(1)
        result = remove_block(args.apt, args.start)
        print(json.dumps(result, indent=2))

    elif args.action == 'list':
        result = list_blocks(args.apt)
        print(json.dumps(result, indent=2))

    elif args.action == 'regenerate':
        result = regenerate_ics_for_apt(args.apt)
        print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
