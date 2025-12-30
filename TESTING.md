# Luas Tracker Test Suite

Comprehensive unit tests for the Luas Tracker backend using **pytest**.

## Running Tests

### Install test dependencies
```bash
pip install -r requirements.txt
```

### Run all tests
```bash
pytest test_luas_tracker.py
```

### Run tests with coverage report
```bash
pytest test_luas_tracker.py --cov=. --cov-report=term-missing
```

### Run specific test class
```bash
pytest test_luas_tracker.py::TestXMLParsing -v
```

### Run specific test
```bash
pytest test_luas_tracker.py::TestXMLParsing::test_parse_valid_xml_single_tram -v
```

### Run tests in watch mode (requires pytest-watch)
```bash
pip install pytest-watch
ptw test_luas_tracker.py
```

## Test Structure

The test suite is organized into 5 test classes:

### 1. **TestXMLParsing** (9 tests)
Tests the XML parser (`luas_client.parse_luas_xml`) which is critical to the entire system.

**What it tests:**
- Single tram parsing
- Multiple trams in different directions
- Special "DUE" status (tram arriving now)
- Filtering out "No trams forecast" entries
- Empty/invalid destinations
- Special characters in destination names
- Invalid XML error handling
- Due time calculation
- Empty XML responses

**Why it matters:** The XML parser is the most critical component. If parsing fails, all downstream data is wrong.

### 2. **TestRoutes** (3 tests)
Tests the API route data and configuration.

**What it tests:**
- LUAS_STOPS dictionary exists and has data
- All stops have required fields (name, line)
- Stop codes are valid format
- Stop names are reasonably unique

**Why it matters:** Invalid stop data would cause API 400 errors.

### 3. **TestEdgeCases** (6 tests)
Tests unusual but valid scenarios that could occur in production.

**What it tests:**
- Very large due_minutes values (999+)
- Zero due_minutes
- Invalid due_minutes formats (should be skipped)
- Whitespace in destinations
- Mixed valid/invalid trams
- Direction name case sensitivity

**Why it matters:** Edge cases are where bugs hide. These ensure robustness.

### 4. **TestDataIntegrity** (4 tests)
Tests that parsed data structure is always consistent.

**What it tests:**
- Return type is always list of dicts
- All dicts have required keys
- due_minutes is always integer and >= 0
- due_time is always valid ISO datetime string

**Why it matters:** Frontend depends on consistent data structure. Inconsistency causes crashes.

## Test Coverage

Current test coverage:
- **luas_client.py**: ~95% (XML parsing thoroughly tested)
- **routes.py**: ~40% (static data tested, endpoints would need integration tests)
- **database.py**: Not tested here (would need integration tests with actual DB)

## Example: Understanding a Test

```python
def test_parse_multiple_trams(self):
    """Test parsing XML with multiple trams in different directions"""
    # 1. ARRANGE: Set up test data
    xml = """<stopInfo>..."""
    
    # 2. ACT: Call the function being tested
    result = parse_luas_xml(xml)
    
    # 3. ASSERT: Verify the result
    assert len(result) == 4
    inbound = [t for t in result if t["direction"] == "Inbound"]
    assert len(inbound) == 3
```

This follows the **AAA Pattern**: Arrange, Act, Assert.

## Adding New Tests

When adding features, add corresponding tests:

```python
def test_new_feature(self):
    """Test description of what you're testing"""
    # Arrange
    test_input = ...
    
    # Act
    result = function_to_test(test_input)
    
    # Assert
    assert result == expected_output
```

## Why These Tests Matter for Your Learning

1. **Best Practices**: Shows you understand testing patterns
2. **Reliability**: Proves your code works, not just "feels right"
3. **Refactoring Confidence**: Tests catch regressions when you change code
4. **Documentation**: Tests show how code is supposed to be used
5. **Interview Gold**: Employers love seeing test coverage

## CI/CD Integration

Tests run automatically on every commit via GitHub Actions (`.github/workflows/tests.yml`).

To enable:
1. Push `.github/workflows/tests.yml` to your repo
2. GitHub will automatically run tests on each push
3. Tests must pass before merging PRs (optional protection rule)

## Accuracy Calculation Improvements (2025-12-30)

The accuracy calculation algorithm was enhanced to better capture arrival events, especially for stops with fewer tram frequencies like Cabra:

### Changes Made:

1. **Increased Calculation Frequency**: Changed from every 5 minutes to **every 1 minute**
   - More frequent checks = less chance of missing arrival transitions
   - Duplicate detection window reduced from 5 minutes to 2 minutes

2. **Multi-Level Arrival Detection**: Now tracks three types of transitions:
   - **Primary**: `>0 → 0` (standard arrival - most accurate)
   - **Secondary**: `2 → 1` (near-arrival - more data points)
   - **Tertiary**: `1 → 0` (imminent arrival - very precise)

3. **Cabra-Specific Debug Logging**: Added detailed logging for Cabra stop to diagnose why accuracy data wasn't being captured:
   - Logs poll counts for each destination/direction
   - Logs forecast progression for last 5 polls
   - Logs when arrival transitions are detected

4. **Poll Timing Validation**: Skip accuracy calculations when polls are >2 minutes apart (indicates missed polling cycles)

### Why Cabra Was Returning Empty Data:

The `/accuracy/summary?stop_code=cab` endpoint was correctly working but returning empty data because:
- No accuracy records existed for Cabra in the database
- The previous algorithm only detected `>0 → 0` transitions with 5-minute checks
- Cabra has lower tram frequency, so fewer arrival events were captured
- The new multi-level detection significantly increases data capture

### Testing the Fix:

After deploying these changes, monitor logs for:
```
DEBUG Cabra: [destination] ([direction]) - [N] polls found
DEBUG Cabra: ARRIVAL DETECTED! [destination] ([direction]) [X]→0
✓ Accuracy [transition_type]: [destination] ([direction]) at cab - forecast Xm, actual Ym ([status])
```

## Potential Next Steps

1. **Integration Tests**: Test full API endpoints with mock database
2. **Performance Tests**: Ensure XML parsing is fast enough
3. **Accuracy Algorithm Tests**: Test the new multi-level arrival detection logic
4. **Database Tests**: Test data storage and querying

## References

- [pytest documentation](https://docs.pytest.org/)
- [Python testing best practices](https://docs.python-guide.org/writing/tests/)
- [AAA Pattern](https://www.freecodecamp.org/news/arrange-act-assert-pattern-for-unit-tests/)
