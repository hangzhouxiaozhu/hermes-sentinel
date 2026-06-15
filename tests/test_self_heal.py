"""Self-heal tests — skill integrity, log health checks."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


class TestQuickCheck(unittest.TestCase):
    """quick_check() must handle various failure modes."""

    def test_healthy_when_no_skills(self):
        from self_heal import quick_check
        with patch("self_heal.SKILLS_DIR", Path(tempfile.mkdtemp())):
            result = quick_check()
            self.assertTrue(result["healthy"])

    def test_log_health_failure_reported(self):
        from self_heal import quick_check
        with patch("self_heal.HERMES_HOME", Path("/nonexistent-path-xyz-12345")):
            result = quick_check()
            self.assertFalse(result["healthy"])
            issues = " ".join(result.get("issues", []))
            self.assertIn("log", issues)

    def test_returns_expected_structure(self):
        from self_heal import quick_check
        result = quick_check()
        self.assertIn("healthy", result)
        self.assertIn("issues", result)
        self.assertIn("severity", result)

    def test_broken_skill_reported(self):
        """Malformed SKILL.md should be detected."""
        from self_heal import quick_check
        skill_dir = Path(tempfile.mkdtemp())
        skills_root = skill_dir / "skills"
        skills_root.mkdir()
        skill_md = skills_root / "test-skill" / "SKILL.md"
        skill_md.parent.mkdir(parents=True, exist_ok=True)
        skill_md.write_text("no frontmatter here")

        with patch("self_heal.SKILLS_DIR", skills_root):
            result = quick_check()
            issues = " ".join(result.get("issues", []))
            self.assertIn("broken", issues)


class TestLogHealth(unittest.TestCase):
    def test_healthy_log_dir(self):
        from self_heal import _check_log_health
        result = _check_log_health()
        self.assertTrue(result["healthy"])

    def test_missing_log_dir_creates_it(self):
        from self_heal import _check_log_health
        with patch("self_heal.HERMES_HOME", Path(tempfile.mkdtemp())):
            result = _check_log_health()
            self.assertTrue(result["healthy"])


class TestCheckSkills(unittest.TestCase):
    def test_no_frontmatter(self):
        from self_heal import _check_skills
        skill_root = Path(tempfile.mkdtemp())
        skill_md = skill_root / "test-skill" / "SKILL.md"
        skill_md.parent.mkdir(parents=True, exist_ok=True)
        skill_md.write_text("no frontmatter")

        with patch("self_heal.SKILLS_DIR", skill_root):
            results = _check_skills()
        self.assertGreaterEqual(len(results), 1)
        self.assertNotEqual(results[0]["status"], "ok")

    def test_malformed_frontmatter(self):
        from self_heal import _check_skills
        skill_root = Path(tempfile.mkdtemp())
        skill_md = skill_root / "test-skill" / "SKILL.md"
        skill_md.parent.mkdir(parents=True, exist_ok=True)
        skill_md.write_text("---\nno closing frontmatter")

        with patch("self_heal.SKILLS_DIR", skill_root):
            results = _check_skills()
        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "broken")

    def test_valid_skill(self):
        from self_heal import _check_skills
        skill_root = Path(tempfile.mkdtemp())
        skill_md = skill_root / "good-skill" / "SKILL.md"
        skill_md.parent.mkdir(parents=True, exist_ok=True)
        skill_md.write_text("---\nname: good-skill\n---\n# Hello")

        with patch("self_heal.SKILLS_DIR", skill_root):
            results = _check_skills()
        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "ok")
