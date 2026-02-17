import avail_checker
import json
import datetime

# Color codes for terminal output
GREEN = '\033[92m'
RED = '\033[91m'
RESET = '\033[0m'
BOLD = '\033[1m'

def print_result(scenario, result):
    print(f"{BOLD}Scenario: {scenario['description']}{RESET}")
    print(f"  Apartment: {result.get('apartment', 'Unknown')}")
    print(f"  Dates:     {result.get('check_in')} to {result.get('check_out')}")
    
    if result.get('available'):
        print(f"  Status:    {GREEN}AVAILABLE{RESET}")
    else:
        print(f"  Status:    {RED}NOT AVAILABLE{RESET}")
        print(f"  Reason:    {result.get('reason')}")
        if result.get('conflicts'):
            print(f"  Conflicts: {result['conflicts']}")
    print("-" * 40)

def run_tests():
    # Load config
    config = avail_checker.load_config()
    
    # Define scenarios relative to "today" (assuming roughly 2026-01-30 based on system time)
    # We will pick some dates. Since I don't know the exact real bookings, 
    # I will rely on the output to show the logic works.
    
    scenarios = [
        {
            "description": "Checking Amazon Minimalist - Next Month (Likely Available)",
            "apt": "amazon_minimalist",
            "start": "2026-03-01",
            "end": "2026-03-05"
        },
        {
            "description": "Checking Family Amazon Minimalist - Next Month (Likely Available)",
            "apt": "family_amazon_minimalist",
            "start": "2026-06-09",
            "end": "2026-06-13"
        },
        {
            "description": "Checking family Amazon Minimalist - Far Future (Likely Available)",
            "apt": "family_amazon_minimalist",
            "start": "2026-02-17",
            "end": "2026-02-20"
        },
         {
            "description": "Checking Invalid Dates",
            "apt": "amazon_minimalist",
            "start": "invalid-date",
            "end": "2026-02-01"
        },{
            "description": "Checking Amazon Minimalist - Far Future (Likely Available)",
            "apt": "amazon_minimalist",
            "start": "2026-03-20",
            "end": "2026-03-25"
        }
    ]

    print(f"{BOLD}Running Availability Tests...{RESET}\n")
    print("-" * 40)

    for sc in scenarios:
        # Call the function directly from the imported module
        result = avail_checker.check_apartment_availability(
            sc['apt'], 
            sc['start'], 
            sc['end'], 
            config
        )
        print_result(sc, result)

if __name__ == "__main__":
    run_tests()
