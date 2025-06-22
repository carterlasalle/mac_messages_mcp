"""
Integration tests for Mac Messages MCP server
Tests all MCP tools to ensure they don't crash and handle edge cases properly
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from mac_messages_mcp.messages import (
    check_addressbook_access,
    check_messages_db_access,
    find_contact_by_name,
    fuzzy_search_messages,
    get_recent_messages,
)


def test_import_fixes():
    """Test that the critical import fixes work"""
    print("Testing import fixes...")
    
    # Test that thefuzz import works
    try:
        from thefuzz import fuzz
        print("✅ thefuzz import works")
        return True
    except ImportError as e:
        print(f"❌ thefuzz import failed: {e}")
        return False


def test_input_validation():
    """Test input validation prevents crashes"""
    print("Testing input validation...")
    
    # Test negative hours
    result = get_recent_messages(hours=-1)
    assert "Error: Hours cannot be negative" in result
    print("✅ Negative hours validation works")
    
    # Test overflow hours
    result = get_recent_messages(hours=999999999)
    assert "Error: Hours value too large" in result
    print("✅ Overflow hours validation works")
    
    # Test empty search term
    result = fuzzy_search_messages("")
    assert "Error: Search term cannot be empty" in result
    print("✅ Empty search term validation works")
    
    # Test invalid threshold
    result = fuzzy_search_messages("test", threshold=-0.1)
    assert "Error: Threshold must be between 0.0 and 1.0" in result
    print("✅ Invalid threshold validation works")
    
    return True


def test_contact_selection_validation():
    """Test contact selection validation"""
    print("Testing contact selection validation...")
    
    # Test invalid contact formats
    test_cases = [
        ("contact:", "Error: Invalid contact selection format"),
        ("contact:abc", "Error: Contact selection must be a number"),
        ("contact:-1", "Error: Contact selection must be a positive number"),
        ("contact:0", "Error: Contact selection must be a positive number"),
    ]
    
    for contact, expected_error in test_cases:
        result = get_recent_messages(contact=contact)
        assert expected_error in result, f"Expected '{expected_error}' in result for '{contact}'"
    
    print("✅ Contact selection validation works")
    return True


def test_no_crashes():
    """Test that basic functionality doesn't crash"""
    print("Testing basic functionality doesn't crash...")
    
    # Test basic message retrieval
    try:
        result = get_recent_messages(hours=1)
        assert isinstance(result, str)
        assert "NameError" not in result
        assert "name 'fuzz' is not defined" not in result
        print("✅ get_recent_messages doesn't crash")
    except Exception as e:
        print(f"❌ get_recent_messages crashed: {e}")
        return False
    
    # Test fuzzy search
    try:
        result = fuzzy_search_messages("test", hours=1)
        assert isinstance(result, str)
        assert "NameError" not in result
        assert "name 'fuzz' is not defined" not in result
        print("✅ fuzzy_search_messages doesn't crash")
    except Exception as e:
        print(f"❌ fuzzy_search_messages crashed: {e}")
        return False
    
    # Test database access checks
    try:
        result = check_messages_db_access()
        assert isinstance(result, str)
        print("✅ check_messages_db_access doesn't crash")
    except Exception as e:
        print(f"❌ check_messages_db_access crashed: {e}")
        return False
    
    try:
        result = check_addressbook_access()
        assert isinstance(result, str)
        print("✅ check_addressbook_access doesn't crash")
    except Exception as e:
        print(f"❌ check_addressbook_access crashed: {e}")
        return False
    
    return True


def test_time_ranges():
    """Test various time ranges that previously failed"""
    print("Testing various time ranges...")
    
    time_ranges = [1, 24, 168, 720, 2160, 4320, 8760]  # 1h to 1 year
    
    for hours in time_ranges:
        try:
            result = get_recent_messages(hours=hours)
            assert isinstance(result, str)
            assert "Python int too large" not in result
            assert "NameError" not in result
        except Exception as e:
            print(f"❌ Time range {hours} hours failed: {e}")
            return False
    
    print("✅ All time ranges work without crashing")
    return True


def run_all_tests():
    """Run all tests and report results"""
    print("🚀 Running Mac Messages MCP Integration Tests")
    print("=" * 50)
    
    tests = [
        test_import_fixes,
        test_input_validation,
        test_contact_selection_validation,
        test_no_crashes,
        test_time_ranges,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
                print(f"✅ {test.__name__} PASSED")
            else:
                failed += 1
                print(f"❌ {test.__name__} FAILED")
        except Exception as e:
            failed += 1
            print(f"❌ {test.__name__} CRASHED: {e}")
        print()
    
    print("=" * 50)
    print(f"🎯 Test Results: {passed} passed, {failed} failed")
    
    if failed == 0:
        print("🎉 ALL TESTS PASSED! The fixes are working correctly.")
        return True
    else:
        print("💥 SOME TESTS FAILED! There are still issues to fix.")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1) 