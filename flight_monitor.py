"""
Professional Flight Price Monitor with Amadeus API
Searches real flight prices from 400+ airlines
Sends notifications via Telegram
"""

import os
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from amadeus import Client, ResponseError
import time

# Load environment variables from .env file
load_dotenv()

# ===========================
# CONFIGURATION FROM .ENV
# ===========================

class Config:
    """Load all configuration from environment variables"""
    
    # Telegram
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
    
    # Amadeus API
    AMADEUS_API_KEY = os.getenv('AMADEUS_API_KEY')
    AMADEUS_API_SECRET = os.getenv('AMADEUS_API_SECRET')
    AMADEUS_ENV = os.getenv('AMADEUS_ENV', 'test')  # 'test' or 'production'
    
    # Flight Search
    FROM_CITY = os.getenv('FROM_CITY', 'Hyderabad')
    FROM_CODE = os.getenv('FROM_CODE', 'HYD')
    TO_CITY = os.getenv('TO_CITY', 'Varanasi')
    TO_CODE = os.getenv('TO_CODE', 'VNS')
    DATE_RANGE_START = os.getenv('DATE_RANGE_START', '2026-02-01')
    DATE_RANGE_END = os.getenv('DATE_RANGE_END', '2026-02-15')
    PASSENGERS = int(os.getenv('PASSENGERS', '5'))
    MAX_PRICE = int(os.getenv('MAX_PRICE_PER_PERSON', '1000'))
    CURRENCY = os.getenv('CURRENCY', 'INR')
    
    # System
    ENVIRONMENT = os.getenv('ENVIRONMENT', 'development')
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    
    @classmethod
    def validate(cls):
        """Check if all required config is present"""
        errors = []
        
        if not cls.TELEGRAM_BOT_TOKEN or cls.TELEGRAM_BOT_TOKEN == 'your_bot_token_here':
            errors.append("❌ TELEGRAM_BOT_TOKEN not set in .env file")
        
        if not cls.TELEGRAM_CHAT_ID or cls.TELEGRAM_CHAT_ID == 'your_chat_id_here':
            errors.append("❌ TELEGRAM_CHAT_ID not set in .env file")
        
        if not cls.AMADEUS_API_KEY or cls.AMADEUS_API_KEY == 'your_amadeus_api_key_here':
            errors.append("❌ AMADEUS_API_KEY not set in .env file")
        
        if not cls.AMADEUS_API_SECRET or cls.AMADEUS_API_SECRET == 'your_amadeus_api_secret_here':
            errors.append("❌ AMADEUS_API_SECRET not set in .env file")
        
        return errors


# ===========================
# UTILITY FUNCTIONS
# ===========================

def log(message, level="INFO"):
    """Simple logging function"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] [{level}] {message}")


def generate_dates_in_range():
    """Generate all dates between start and end"""
    start = datetime.strptime(Config.DATE_RANGE_START, '%Y-%m-%d')
    end = datetime.strptime(Config.DATE_RANGE_END, '%Y-%m-%d')
    
    dates = []
    current = start
    while current <= end:
        dates.append(current.strftime('%Y-%m-%d'))
        current += timedelta(days=1)
    
    return dates


# ===========================
# TELEGRAM NOTIFICATIONS
# ===========================

def send_telegram_message(message):
    """Send message to Telegram"""
    try:
        url = f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            'chat_id': Config.TELEGRAM_CHAT_ID,
            'text': message,
            'parse_mode': 'Markdown',
            'disable_web_page_preview': True
        }
        
        response = requests.post(url, data=data, timeout=10)
        
        if response.status_code == 200:
            log("✅ Message sent to Telegram successfully")
            return True
        else:
            log(f"Telegram API Error: {response.text}", "ERROR")
            return False
            
    except Exception as e:
        log(f"Failed to send Telegram message: {e}", "ERROR")
        return False


def send_long_message(message):
    """Split and send long messages (Telegram has 4096 char limit)"""
    max_length = 4000
    
    if len(message) <= max_length:
        return send_telegram_message(message)
    
    # Split into chunks
    parts = []
    current_part = ""
    
    for line in message.split('\n'):
        if len(current_part) + len(line) + 1 > max_length:
            parts.append(current_part)
            current_part = line + '\n'
        else:
            current_part += line + '\n'
    
    if current_part:
        parts.append(current_part)
    
    # Send each part
    for i, part in enumerate(parts, 1):
        log(f"Sending part {i}/{len(parts)} to Telegram")
        send_telegram_message(part)
        time.sleep(1)  # Avoid rate limiting
    
    return True


# ===========================
# AMADEUS API INTEGRATION
# ===========================

def get_amadeus_client():
    """Initialize Amadeus API client"""
    try:
        client = Client(
            client_id=Config.AMADEUS_API_KEY,
            client_secret=Config.AMADEUS_API_SECRET,
            hostname='test' if Config.AMADEUS_ENV == 'test' else 'production'
        )
        return client
    except Exception as e:
        log(f"Failed to initialize Amadeus client: {e}", "ERROR")
        return None


def search_flights_amadeus(date):
    """
    Search flights using Amadeus Flight Offers Search API
    
    API Documentation: https://developers.amadeus.com/self-service/category/flights
    """
    
    client = get_amadeus_client()
    if not client:
        return []
    
    try:
        log(f"Searching flights for {date}...", "DEBUG")
        
        # Make API request
        response = client.shopping.flight_offers_search.get(
            originLocationCode=Config.FROM_CODE,
            destinationLocationCode=Config.TO_CODE,
            departureDate=date,
            adults=Config.PASSENGERS,
            currencyCode=Config.CURRENCY,
            max=50  # Get up to 50 results
        )
        
        # Parse response
        deals = parse_amadeus_response(response.data, date)
        
        if deals:
            log(f"✅ Found {len(deals)} deals for {date}")
        else:
            log(f"❌ No deals under ₹{Config.MAX_PRICE} for {date}")
        
        return deals
        
    except ResponseError as error:
        log(f"Amadeus API Error for {date}: {error}", "ERROR")
        return []
    except Exception as e:
        log(f"Error searching flights for {date}: {e}", "ERROR")
        return []


def parse_amadeus_response(data, date):
    """Parse Amadeus API response to extract flight deals"""
    
    deals = []
    
    try:
        for offer in data:
            # Get total price
            total_price_str = offer.get('price', {}).get('total', '0')
            total_price = float(total_price_str)
            
            # Calculate per person price
            price_per_person = total_price / Config.PASSENGERS
            
            # Only include if under max price
            if price_per_person <= Config.MAX_PRICE:
                # Get first segment (outbound flight)
                itineraries = offer.get('itineraries', [])
                if not itineraries:
                    continue
                
                first_itinerary = itineraries[0]
                segments = first_itinerary.get('segments', [])
                
                if not segments:
                    continue
                
                first_segment = segments[0]
                
                # Extract airline info
                carrier_code = first_segment.get('carrierCode', 'XX')
                airline_name = get_airline_name(carrier_code)
                
                # Extract timing
                departure = first_segment.get('departure', {})
                arrival_time = first_itinerary.get('segments', [{}])[-1].get('arrival', {})
                
                departure_time = departure.get('at', '')[:16]  # 2026-02-01T06:30
                departure_hour = departure_time.split('T')[1] if 'T' in departure_time else 'N/A'
                
                # Calculate duration
                duration_str = first_itinerary.get('duration', 'PT0H0M')
                duration = parse_duration(duration_str)
                
                # Count stops
                stops = len(segments) - 1
                
                # Get booking class
                booking_class = segments[0].get('cabin', 'ECONOMY')
                
                deal = {
                    'date': date,
                    'price': int(price_per_person),
                    'total_price': int(total_price),
                    'airline': airline_name,
                    'carrier_code': carrier_code,
                    'duration': duration,
                    'stops': stops,
                    'departure_time': departure_hour,
                    'cabin_class': booking_class,
                    'source': 'Amadeus'
                }
                
                deals.append(deal)
                log(f"  ✓ ₹{int(price_per_person)} - {airline_name} ({carrier_code})", "DEBUG")
        
    except Exception as e:
        log(f"Error parsing Amadeus response: {e}", "ERROR")
    
    return deals


def get_airline_name(carrier_code):
    """Convert airline code to name"""
    airlines = {
        '6E': 'IndiGo',
        'AI': 'Air India',
        'SG': 'SpiceJet',
        'UK': 'Vistara',
        'QP': 'Akasa Air',
        'IX': 'Air India Express',
        '9I': 'Alliance Air',
        'I5': 'AirAsia India',
        'G8': 'Go First'
    }
    return airlines.get(carrier_code, carrier_code)


def parse_duration(duration_str):
    """Parse ISO 8601 duration to human readable format"""
    # Example: PT3H25M -> 3h 25m
    try:
        duration_str = duration_str.replace('PT', '')
        
        hours = 0
        minutes = 0
        
        if 'H' in duration_str:
            parts = duration_str.split('H')
            hours = int(parts[0])
            duration_str = parts[1]
        
        if 'M' in duration_str:
            minutes = int(duration_str.replace('M', ''))
        
        return f"{hours}h {minutes}m"
    except:
        return "N/A"


def search_all_dates():
    """Search flights for all dates in range"""
    
    dates = generate_dates_in_range()
    all_deals = []
    
    log(f"Starting search for {len(dates)} dates...")
    log(f"Date range: {Config.DATE_RANGE_START} to {Config.DATE_RANGE_END}")
    print()
    
    for i, date in enumerate(dates, 1):
        log(f"[{i}/{len(dates)}] Checking {date}...")
        
        deals = search_flights_amadeus(date)
        all_deals.extend(deals)
        
        # Rate limiting - Amadeus allows 10 requests/second on test
        # But we'll be nice and wait 1 second between requests
        if i < len(dates):
            time.sleep(1)
    
    return all_deals


# ===========================
# MESSAGE FORMATTING
# ===========================

def format_results_message(deals):
    """Format flight deals into Telegram message"""
    
    if not deals:
        message = "❌ *No Deals Found*\n\n"
        message += f"🛫 {Config.FROM_CITY} → {Config.TO_CITY}\n"
        message += f"📅 {Config.DATE_RANGE_START} to {Config.DATE_RANGE_END}\n"
        message += f"👥 {Config.PASSENGERS} passengers\n"
        message += f"💰 Target: ≤ ₹{Config.MAX_PRICE}/person\n\n"
        message += "💡 *Suggestions:*\n"
        message += "• Increase your budget in .env file\n"
        message += "• Try different dates\n"
        message += "• Check again later (prices change!)\n\n"
        message += "_Using Amadeus API - Real prices from 400+ airlines_"
        return message
    
    # Sort by price
    deals.sort(key=lambda x: x['price'])
    
    # Build message
    message = "✈️ *FLIGHT DEALS FOUND!*\n"
    message += "━━━━━━━━━━━━━━━━━━━━\n\n"
    message += f"🛫 *{Config.FROM_CITY} ({Config.FROM_CODE}) → {Config.TO_CITY} ({Config.TO_CODE})*\n"
    message += f"📅 {Config.DATE_RANGE_START} to {Config.DATE_RANGE_END}\n"
    message += f"👥 {Config.PASSENGERS} passengers\n"
    message += f"🎯 *{len(deals)} deals* under ₹{Config.MAX_PRICE}\n\n"
    message += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    # Show top 15 deals
    message += "*🏆 TOP 15 BEST DEALS:*\n\n"
    
    for i, deal in enumerate(deals[:15], 1):
        date_obj = datetime.strptime(deal['date'], '%Y-%m-%d')
        formatted_date = date_obj.strftime('%b %d, %a')
        
        message += f"*{i}. ₹{deal['price']}/person* ({formatted_date})\n"
        message += f"   💰 Total: ₹{deal['total_price']:,} for {Config.PASSENGERS} pax\n"
        message += f"   ✈️ {deal['airline']} ({deal['carrier_code']})"
        
        if deal['stops'] == 0:
            message += " • Non-stop\n"
        else:
            message += f" • {deal['stops']} stop(s)\n"
        
        message += f"   🕐 Departs {deal['departure_time']} • {deal['duration']}\n"
        message += f"   💺 {deal['cabin_class']}\n\n"
    
    if len(deals) > 15:
        message += f"\n_...and {len(deals) - 15} more deals available!_\n"
    
    # Statistics
    message += "\n━━━━━━━━━━━━━━━━━━━━\n"
    message += "*📊 STATISTICS:*\n\n"
    
    # Best price
    best = deals[0]
    message += f"🏆 Cheapest: ₹{best['price']} ({best['airline']})\n"
    
    # Average price
    avg = sum(d['price'] for d in deals) / len(deals)
    message += f"📊 Average: ₹{int(avg)}\n"
    
    # Best airline
    airline_counts = {}
    for deal in deals:
        airline = deal['airline']
        airline_counts[airline] = airline_counts.get(airline, 0) + 1
    
    if airline_counts:
        best_airline = max(airline_counts.items(), key=lambda x: x[1])
        message += f"✈️ Most deals: {best_airline[0]} ({best_airline[1]} flights)\n"
    
    # Non-stop flights count
    nonstop = sum(1 for d in deals if d['stops'] == 0)
    if nonstop > 0:
        message += f"🚀 Non-stop flights: {nonstop}\n"
    
    message += f"\n🕐 Checked: {datetime.now().strftime('%I:%M %p, %b %d, %Y')}\n"
    message += f"🌐 Source: Amadeus (400+ airlines)\n"
    message += f"💡 Run again anytime to refresh prices"
    
    return message


# ===========================
# MAIN EXECUTION
# ===========================

def main():
    """Main function"""
    
    print("="*70)
    print("🚀 FLIGHT PRICE MONITOR - AMADEUS API")
    print("="*70)
    print()
    
    # Validate configuration
    log("Checking configuration...")
    errors = Config.validate()
    
    if errors:
        print()
        print("⚠️  CONFIGURATION ERRORS:")
        for error in errors:
            print(f"   {error}")
        print()
        print("📝 How to fix:")
        print("   1. Open .env file")
        print("   2. Add your actual API keys")
        print("   3. Save and run again")
        print()
        print("🔗 Get Amadeus API key:")
        print("   → https://developers.amadeus.com/register")
        print("   → Create app → Copy API Key & Secret")
        print()
        return
    
    log("✅ Configuration validated")
    print()
    
    # Display config
    log(f"Route: {Config.FROM_CITY} ({Config.FROM_CODE}) → {Config.TO_CITY} ({Config.TO_CODE})")
    log(f"Dates: {Config.DATE_RANGE_START} to {Config.DATE_RANGE_END}")
    log(f"Passengers: {Config.PASSENGERS}")
    log(f"Max Price: ₹{Config.MAX_PRICE}/person")
    log(f"Currency: {Config.CURRENCY}")
    log(f"API Environment: {Config.AMADEUS_ENV}")
    print()
    
    # Search flights
    log("🔍 Starting Amadeus flight search...")
    print()
    
    deals = search_all_dates()
    
    # Results
    print()
    print("="*70)
    log(f"SEARCH COMPLETE - Found {len(deals)} deals under ₹{Config.MAX_PRICE}")
    print("="*70)
    print()
    
    if deals:
        best = min(deals, key=lambda x: x['price'])
        log(f"🏆 Best deal: ₹{best['price']}/person on {best['date']} via {best['airline']}")
        log(f"💰 Total for {Config.PASSENGERS} passengers: ₹{best['total_price']:,}")
    
    # Format message
    message = format_results_message(deals)
    
    # Display preview
    print()
    print("📱 Telegram Message Preview:")
    print("-" * 70)
    print(message.replace('*', '').replace('_', ''))
    print("-" * 70)
    print()
    
    # Send to Telegram
    log("📤 Sending to Telegram...")
    success = send_long_message(message)
    
    if success:
        log("✅ Results sent to Telegram successfully!")
        log("📱 Check your Telegram app for the message")
    else:
        log("❌ Failed to send to Telegram", "ERROR")
    
    print()
    print("="*70)
    print("✨ DONE!")
    print("="*70)
    print()
    print(f"💡 API calls used: {len(generate_dates_in_range())}/{2000} (this month)")
    print("🔄 Run script again anytime to check updated prices")
    print()


if __name__ == "__main__":
    main()