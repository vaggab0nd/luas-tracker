import httpx
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

LUAS_API_URL = "https://luasforecasts.rpa.ie/xml/get.ashx"
CABRA_STOP_CODE = "cab"


class LuasAPIError(Exception):
    """Raised when Luas API call fails."""
    pass


async def fetch_luas_forecast(stop_code: str = CABRA_STOP_CODE) -> List[Dict]:
    """
    Fetch real-time Luas forecasts for a given stop.
    
    Returns a list of dicts with:
    - destination: Final destination
    - direction: Inbound/Outbound
    - due_minutes: Minutes until arrival
    - due_time: Calculated arrival time (ISO format)
    """
    try:
        # Use follow_redirects=True to handle 301 redirects from HTTP to HTTPS
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            # Note: We're making the request from backend to work around CORS
            # The API may have IP/origin restrictions
            response = await client.get(
                LUAS_API_URL,
                params={
                    "action": "forecast",
                    "stop": stop_code,
                    "encrypt": "false"
                }
            )
            response.raise_for_status()
            
            return parse_luas_xml(response.text)
    
    except httpx.HTTPError as e:
        logger.error(f"HTTP error fetching Luas data: {e}")
        raise LuasAPIError(f"Failed to fetch Luas API: {e}")
    except Exception as e:
        logger.error(f"Unexpected error fetching Luas data: {e}")
        raise LuasAPIError(f"Unexpected error: {e}")


def parse_luas_xml(xml_content: str) -> List[Dict]:
    """
    Parse XML response from Luas API.
    
    Expected structure:
    <root>
      <message>
        <tram>
          <destination>...</destination>
          <direction>Inbound/Outbound</direction>
          <dueMinutes>X</dueMinutes>
          <dueTime>HH:MM</dueTime>
        </tram>
      </message>
    </root>
    """
    forecasts = []
    
    try:
        root = ET.fromstring(xml_content)
        
        # Debug: Always log raw XML for debugging
        logger.info(f"API Response (first 300 chars): {xml_content[:300]}")
        logger.info(f"Root tag: {root.tag}")
        
        # Navigate the XML structure - trams are inside <direction> elements
        # <stopInfo><direction name="Inbound"><tram dueMins="10" destination="Destination" /></direction></stopInfo>
        for direction_elem in root.findall("direction"):
            direction_name = direction_elem.get("name", "Unknown")
            
            for tram in direction_elem.findall("tram"):
                try:
                    # Get attributes from tram element
                    destination = tram.get("destination", "Unknown")
                    due_minutes_str = tram.get("dueMins", "0")
                    
                    # Skip "No trams forecast" entries
                    if destination == "No trams forecast" or not destination or destination == "Unknown":
                        continue
                    
                    # Handle dueMins - can be "DUE", a number, or empty
                    if due_minutes_str and due_minutes_str.upper() == "DUE":
                        due_minutes = 0
                    elif due_minutes_str:
                        try:
                            due_minutes = int(due_minutes_str)
                        except ValueError:
                            logger.warning(f"Invalid dueMins value: {due_minutes_str}")
                            continue
                    else:
                        due_minutes = 0
                    
                    # Calculate due time
                    due_time = datetime.now() + timedelta(minutes=due_minutes)
                    
                    forecasts.append({
                        "destination": destination,
                        "direction": direction_name,
                        "due_minutes": due_minutes,
                        "due_time": due_time.isoformat()
                    })
                    logger.debug(f"Parsed tram: {destination} ({direction_name}) in {due_minutes}m")
            
                except (ValueError, AttributeError) as e:
                    logger.warning(f"Failed to parse tram element: {e}")
                    continue
        
        if not forecasts:
            logger.warning(f"No valid trams found in API response")
        
        return forecasts
    
    except ET.ParseError as e:
        logger.error(f"XML parse error: {e}")
        logger.error(f"Attempted to parse: {xml_content[:200]}")
        raise LuasAPIError(f"Invalid XML response from Luas API: {e}")
