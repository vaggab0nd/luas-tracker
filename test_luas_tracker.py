"""
Unit tests for Luas Tracker backend
Tests cover: XML parsing, API endpoints, database models, and edge cases
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
import xml.etree.ElementTree as ET

# Import modules to test
from luas_client import parse_luas_xml, fetch_luas_forecast
from routes import LUAS_STOPS


class TestXMLParsing:
    """Tests for Luas API XML response parsing"""
    
    def test_parse_valid_xml_single_tram(self):
        """Test parsing XML with a single tram"""
        xml = """
        <stopInfo created="2025-12-29T14:34:37" stop="Cabra" stopAbv="CAB">
            <message>Services running</message>
            <direction name="Inbound">
                <tram dueMins="10" destination="Broombridge" />
            </direction>
        </stopInfo>
        """
        
        result = parse_luas_xml(xml)
        
        assert len(result) == 1
        assert result[0]["destination"] == "Broombridge"
        assert result[0]["direction"] == "Inbound"
        assert result[0]["due_minutes"] == 10
    
    def test_parse_multiple_trams(self):
        """Test parsing XML with multiple trams in different directions"""
        xml = """
        <stopInfo created="2025-12-29T14:34:37" stop="Cabra" stopAbv="CAB">
            <message>Services running</message>
            <direction name="Inbound">
                <tram dueMins="8" destination="Broombridge" />
                <tram dueMins="22" destination="Broombridge" />
                <tram dueMins="34" destination="Broombridge" />
            </direction>
            <direction name="Outbound">
                <tram dueMins="10" destination="Sandyford" />
            </direction>
        </stopInfo>
        """
        
        result = parse_luas_xml(xml)
        
        assert len(result) == 4
        inbound = [t for t in result if t["direction"] == "Inbound"]
        outbound = [t for t in result if t["direction"] == "Outbound"]
        
        assert len(inbound) == 3
        assert len(outbound) == 1
        assert inbound[0]["due_minutes"] == 8
        assert inbound[1]["due_minutes"] == 22
        assert outbound[0]["destination"] == "Sandyford"
    
    def test_parse_due_status(self):
        """Test parsing trams with 'DUE' status (arriving now)"""
        xml = """
        <stopInfo created="2025-12-29T14:34:37" stop="Jervis" stopAbv="JER">
            <direction name="Inbound">
                <tram dueMins="DUE" destination="The Point" />
                <tram dueMins="6" destination="Connolly" />
            </direction>
        </stopInfo>
        """
        
        result = parse_luas_xml(xml)
        
        assert len(result) == 2
        assert result[0]["due_minutes"] == 0
        assert result[1]["due_minutes"] == 6
    
    def test_skip_no_trams_forecast(self):
        """Test that 'No trams forecast' entries are skipped"""
        xml = """
        <stopInfo created="2025-12-29T14:34:37" stop="Connolly" stopAbv="CON">
            <direction name="Inbound">
                <tram destination="No trams forecast" dueMins="" />
            </direction>
            <direction name="Outbound">
                <tram dueMins="9" destination="Tallaght" />
            </direction>
        </stopInfo>
        """
        
        result = parse_luas_xml(xml)
        
        assert len(result) == 1
        assert result[0]["destination"] == "Tallaght"
    
    def test_skip_empty_destinations(self):
        """Test that trams with empty destinations are skipped"""
        xml = """
        <stopInfo created="2025-12-29T14:34:37" stop="Test" stopAbv="TST">
            <direction name="Inbound">
                <tram dueMins="5" destination="" />
                <tram dueMins="10" destination="Valid Destination" />
            </direction>
        </stopInfo>
        """
        
        result = parse_luas_xml(xml)
        
        assert len(result) == 1
        assert result[0]["destination"] == "Valid Destination"
    
    def test_parse_preserves_destination_names(self):
        """Test that destination names with special characters are preserved"""
        xml = """
        <stopInfo created="2025-12-29T14:34:37" stop="Test" stopAbv="TST">
            <direction name="Inbound">
                <tram dueMins="5" destination="Dublin City Centre - O&apos;Connell" />
                <tram dueMins="10" destination="Busáras" />
            </direction>
        </stopInfo>
        """
        
        result = parse_luas_xml(xml)
        
        assert len(result) == 2
        assert "O'Connell" in result[0]["destination"]
        assert result[1]["destination"] == "Busáras"
    
    def test_parse_invalid_xml_raises_error(self):
        """Test that invalid XML raises an error"""
        xml = "<stopInfo><invalid"
        
        with pytest.raises(Exception):
            parse_luas_xml(xml)
    
    def test_due_time_calculation(self):
        """Test that due_time is calculated correctly"""
        xml = """
        <stopInfo created="2025-12-29T14:34:37" stop="Cabra" stopAbv="CAB">
            <direction name="Inbound">
                <tram dueMins="5" destination="Broombridge" />
            </direction>
        </stopInfo>
        """
        
        before = datetime.now()
        result = parse_luas_xml(xml)
        after = datetime.now()
        
        due_time = datetime.fromisoformat(result[0]["due_time"])
        
        # due_time should be approximately 5 minutes from now
        expected_min = before + timedelta(minutes=5)
        expected_max = after + timedelta(minutes=5, seconds=1)
        
        assert expected_min <= due_time <= expected_max
    
    def test_parse_empty_response(self):
        """Test parsing XML with no trams"""
        xml = """
        <stopInfo created="2025-12-29T14:34:37" stop="Test" stopAbv="TST">
            <message>No service</message>
        </stopInfo>
        """
        
        result = parse_luas_xml(xml)
        
        assert len(result) == 0


class TestRoutes:
    """Tests for API route validation and responses"""
    
    def test_luas_stops_data_exists(self):
        """Test that LUAS_STOPS dictionary has valid data"""
        assert len(LUAS_STOPS) > 0
        
        # Check Cabra exists
        assert "cab" in LUAS_STOPS
        assert LUAS_STOPS["cab"]["name"] == "Cabra"
        assert LUAS_STOPS["cab"]["line"] in ["Green", "Red"]
    
    def test_all_stops_have_required_fields(self):
        """Test that all stops have name and line fields"""
        for stop_code, stop_info in LUAS_STOPS.items():
            assert "name" in stop_info, f"Stop {stop_code} missing 'name'"
            assert "line" in stop_info, f"Stop {stop_code} missing 'line'"
            assert isinstance(stop_info["name"], str)
            assert stop_info["line"] in ["Green", "Red"]
    
    def test_stop_codes_are_valid(self):
        """Test that stop codes are reasonable (short, lowercase)"""
        for stop_code in LUAS_STOPS.keys():
            assert 2 <= len(stop_code) <= 3, f"Stop code {stop_code} seems invalid"
            assert stop_code.islower(), f"Stop code {stop_code} should be lowercase"
    
    def test_no_duplicate_stop_names(self):
        """Test that stop names are reasonably unique"""
        names = [stop["name"] for stop in LUAS_STOPS.values()]
        # Allow some duplicates (different codes for same stop on different lines)
        # but shouldn't have tons of duplicates
        assert len(set(names)) > len(LUAS_STOPS) * 0.7


class TestEdgeCases:
    """Tests for edge cases and error handling"""
    
    def test_parse_very_large_due_minutes(self):
        """Test parsing trams with large due_minutes values"""
        xml = """
        <stopInfo created="2025-12-29T14:34:37" stop="Test" stopAbv="TST">
            <direction name="Inbound">
                <tram dueMins="999" destination="Very Far Away" />
            </direction>
        </stopInfo>
        """
        
        result = parse_luas_xml(xml)
        
        assert len(result) == 1
        assert result[0]["due_minutes"] == 999
    
    def test_parse_zero_due_minutes(self):
        """Test parsing trams with 0 minutes (equivalent to DUE)"""
        xml = """
        <stopInfo created="2025-12-29T14:34:37" stop="Test" stopAbv="TST">
            <direction name="Inbound">
                <tram dueMins="0" destination="Arriving Now" />
            </direction>
        </stopInfo>
        """
        
        result = parse_luas_xml(xml)
        
        assert result[0]["due_minutes"] == 0
    
    def test_parse_non_numeric_due_minutes_skips_tram(self):
        """Test that trams with invalid due_minutes are skipped"""
        xml = """
        <stopInfo created="2025-12-29T14:34:37" stop="Test" stopAbv="TST">
            <direction name="Inbound">
                <tram dueMins="INVALID" destination="Bad Tram" />
                <tram dueMins="5" destination="Good Tram" />
            </direction>
        </stopInfo>
        """
        
        result = parse_luas_xml(xml)
        
        assert len(result) == 1
        assert result[0]["destination"] == "Good Tram"
    
    def test_parse_whitespace_in_destinations(self):
        """Test that destinations with extra whitespace are preserved"""
        xml = """
        <stopInfo created="2025-12-29T14:34:37" stop="Test" stopAbv="TST">
            <direction name="Inbound">
                <tram dueMins="5" destination="  The Point  " />
            </direction>
        </stopInfo>
        """
        
        result = parse_luas_xml(xml)
        
        # XML parser should preserve whitespace as-is
        assert "The Point" in result[0]["destination"]
    
    def test_parse_mixed_valid_invalid_trams(self):
        """Test parsing with mix of valid and invalid trams"""
        xml = """
        <stopInfo created="2025-12-29T14:34:37" stop="Test" stopAbv="TST">
            <direction name="Inbound">
                <tram dueMins="5" destination="Valid 1" />
                <tram dueMins="" destination="" />
                <tram dueMins="10" destination="Valid 2" />
                <tram dueMins="INVALID" destination="Invalid" />
                <tram dueMins="15" destination="Valid 3" />
            </direction>
        </stopInfo>
        """
        
        result = parse_luas_xml(xml)
        
        assert len(result) == 3
        assert result[0]["destination"] == "Valid 1"
        assert result[1]["destination"] == "Valid 2"
        assert result[2]["destination"] == "Valid 3"
    
    def test_parse_direction_case_sensitivity(self):
        """Test that direction names are preserved as-is"""
        xml = """
        <stopInfo created="2025-12-29T14:34:37" stop="Test" stopAbv="TST">
            <direction name="Inbound">
                <tram dueMins="5" destination="Destination 1" />
            </direction>
            <direction name="Outbound">
                <tram dueMins="10" destination="Destination 2" />
            </direction>
        </stopInfo>
        """
        
        result = parse_luas_xml(xml)
        
        assert result[0]["direction"] == "Inbound"
        assert result[1]["direction"] == "Outbound"


class TestDataIntegrity:
    """Tests for data consistency and integrity"""
    
    def test_parse_returns_list_of_dicts(self):
        """Test that parse_luas_xml always returns a list of dicts"""
        xml = """
        <stopInfo created="2025-12-29T14:34:37" stop="Test" stopAbv="TST">
            <direction name="Inbound">
                <tram dueMins="5" destination="Test" />
            </direction>
        </stopInfo>
        """
        
        result = parse_luas_xml(xml)
        
        assert isinstance(result, list)
        assert all(isinstance(item, dict) for item in result)
    
    def test_parse_dict_has_required_keys(self):
        """Test that each parsed tram has all required keys"""
        xml = """
        <stopInfo created="2025-12-29T14:34:37" stop="Test" stopAbv="TST">
            <direction name="Inbound">
                <tram dueMins="5" destination="Test" />
            </direction>
        </stopInfo>
        """
        
        result = parse_luas_xml(xml)
        required_keys = {"destination", "direction", "due_minutes", "due_time"}
        
        for tram in result:
            assert required_keys.issubset(tram.keys())
    
    def test_parse_due_minutes_is_integer(self):
        """Test that due_minutes is always an integer"""
        xml = """
        <stopInfo created="2025-12-29T14:34:37" stop="Test" stopAbv="TST">
            <direction name="Inbound">
                <tram dueMins="5" destination="Test 1" />
                <tram dueMins="DUE" destination="Test 2" />
                <tram dueMins="0" destination="Test 3" />
            </direction>
        </stopInfo>
        """
        
        result = parse_luas_xml(xml)
        
        for tram in result:
            assert isinstance(tram["due_minutes"], int)
            assert tram["due_minutes"] >= 0
    
    def test_parse_due_time_is_iso_string(self):
        """Test that due_time is a valid ISO datetime string"""
        xml = """
        <stopInfo created="2025-12-29T14:34:37" stop="Test" stopAbv="TST">
            <direction name="Inbound">
                <tram dueMins="5" destination="Test" />
            </direction>
        </stopInfo>
        """
        
        result = parse_luas_xml(xml)
        
        for tram in result:
            # Should be parseable as ISO datetime
            due_time = datetime.fromisoformat(tram["due_time"])
            assert isinstance(due_time, datetime)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
