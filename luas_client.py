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
        
        # Debug: Log raw XML for first request
        if len(xml_content) < 500:
            logger.debug(f"Raw API response: {xml_content}")
        
        # Navigate the XML structure
        # The actual structure might vary, so we're flexible
        for tram in root.findall(".//tram"):
            try:
                destination = tram.findtext("destination", "Unknown")
                direction = tram.findtext("direction", "Unknown")
                
                # Get dueMinutes - handle both int and "Due" special case
                due_minutes_str = tram.findtext("dueMinutes", "0")
                if due_minutes_str and due_minutes_str.lower() == "due":
                    due_minutes = 0
                else:
                    try:
                        due_minutes = int(due_minutes_str or "0")
                    except ValueError:
                        logger.warning(f"Invalid dueMinutes value: {due_minutes_str}")
                        due_minutes = 0
                
                due_time_str = tram.findtext("dueTime", "")
                
                # Calculate due time
                if due_time_str and due_time_str.lower() != "due":
                    try:
                        due_time = datetime.strptime(due_time_str, "%H:%M")
                        # Assume same day for now (TODO: handle midnight)
                        now = datetime.now()
                        due_time = due_time.replace(
                            year=now.year,
                            month=now.month,
                            day=now.day
                        )
                        # If due time is in the past, assume it's tomorrow
                        if due_time < now:
                            due_time = due_time + timedelta(days=1)
                    except ValueError:
                        due_time = datetime.now() + timedelta(minutes=due_minutes)
                else:
                    due_time = datetime.now() + timedelta(minutes=due_minutes)
                
                # Only add if we have valid data
                if destination != "Unknown":
                    forecasts.append({
                        "destination": destination,
                        "direction": direction,
                        "due_minutes": due_minutes,
                        "due_time": due_time.isoformat()
                    })
                    logger.debug(f"Parsed tram: {destination} in {due_minutes}m (due {due_time_str})")
            
            except (ValueError, AttributeError) as e:
                logger.warning(f"Failed to parse tram element: {e}")
                continue
        
        if not forecasts:
            logger.warning(f"No trams found in API response (checked {len(list(root.findall('.//tram')))} elements)")
        
        return forecasts
    
    except ET.ParseError as e:
        logger.error(f"XML parse error: {e}")
        logger.error(f"Attempted to parse: {xml_content[:200]}")
        raise LuasAPIError(f"Invalid XML response from Luas API: {e}")
