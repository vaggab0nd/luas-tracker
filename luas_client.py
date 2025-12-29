import httpx
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

LUAS_API_URL = "http://luasforecasts.rpa.ie/xml/get.ashx"
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
        async with httpx.AsyncClient(timeout=10.0) as client:
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
        
        # Navigate the XML structure
        # The actual structure might vary, so we're flexible
        for tram in root.findall(".//tram"):
            try:
                destination = tram.findtext("destination", "Unknown")
                direction = tram.findtext("direction", "Unknown")
                due_minutes = int(tram.findtext("dueMinutes", "0") or "0")
                due_time_str = tram.findtext("dueTime", "")
                
                # Calculate due time if not provided
                if due_time_str:
                    try:
                        due_time = datetime.strptime(due_time_str, "%H:%M")
                        # Assume same day for now
                        due_time = due_time.replace(
                            year=datetime.now().year,
                            month=datetime.now().month,
                            day=datetime.now().day
                        )
                    except ValueError:
                        due_time = datetime.now() + timedelta(minutes=due_minutes)
                else:
                    due_time = datetime.now() + timedelta(minutes=due_minutes)
                
                forecasts.append({
                    "destination": destination,
                    "direction": direction,
                    "due_minutes": due_minutes,
                    "due_time": due_time.isoformat()
                })
            
            except (ValueError, AttributeError) as e:
                logger.warning(f"Failed to parse tram element: {e}")
                continue
        
        if not forecasts:
            logger.warning("No trams found in API response")
        
        return forecasts
    
    except ET.ParseError as e:
        logger.error(f"XML parse error: {e}")
        raise LuasAPIError(f"Invalid XML response from Luas API: {e}")
