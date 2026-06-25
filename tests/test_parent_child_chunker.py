import unittest
import sys
import os

# Add scripts directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "scripts"))

from parent_child_chunker import parse_4gl_to_parents, slice_to_children

class TestParentChildChunker(unittest.TestCase):
    def test_chunker(self):
        mock_4gl = """
DATABASE ds

GLOBALS
    DEFINE g_name CHAR(20)
END GLOBALS

MAIN
    DISPLAY "Hello"
END MAIN

# This is a comment containing FUNCTION keyword in it
{
  Block comment
  FUNCTION fake_func_inside_comment()
}

FUNCTION add(a, b)
    # Inside comment
    RETURN a + b
END FUNCTION

REPORT print_report()
    PRINT "Report content"
END REPORT
"""
        parents = parse_4gl_to_parents(mock_4gl, "test_file.4gl")
        
        # We expect 4 parents: Global, MAIN, FUNCTION, REPORT
        types = [p["type"] for p in parents]
        names = [p["name"] for p in parents]
        
        self.assertIn("GLOBAL", types)
        self.assertIn("MAIN", types)
        self.assertIn("FUNCTION", types)
        self.assertIn("REPORT", types)
        
        # Verify function name extraction
        add_chunk = next(p for p in parents if p["type"] == "FUNCTION")
        self.assertEqual(add_chunk["name"], "add")
        self.assertIn("RETURN a + b", add_chunk["content"])
        
        # Verify that comment functions are not parsed as separate parents
        self.assertNotIn("fake_func_inside_comment", names)
        
        # Test slicing to children
        children = slice_to_children(add_chunk["content"], add_chunk, "test_file.4gl", child_size=50, child_overlap=10)
        self.assertTrue(len(children) > 0)
        
        for c in children:
            self.assertEqual(c["metadata"]["parent_id"], "test_file.4gl_add")
            self.assertEqual(c["metadata"]["source_file"], "test_file.4gl")
            self.assertEqual(c["metadata"]["type"], "FUNCTION")
            self.assertEqual(c["metadata"]["function_name"], "add")

if __name__ == "__main__":
    unittest.main()
