import os
import subprocess
import sys
from pathlib import Path

import pytest


class TestRuntimeEntrypoint:
    """Tests to verify only llm_rpg.main:app is used as the application entrypoint."""

    def test_llm_rpg_main_imports_successfully(self):
        """Verify that llm_rpg.main:app can be imported without errors."""
        # Change to backend directory for proper import
        backend_dir = Path(__file__).parent.parent.parent
        os.chdir(backend_dir)

        # Add backend to path if needed
        if str(backend_dir) not in sys.path:
            sys.path.insert(0, str(backend_dir))

        # Import should succeed
        from llm_rpg.main import app

        assert app is not None
        assert hasattr(app, "title")
        assert app.title == "LLM RPG Engine"

    def test_app_is_fastapi_instance(self):
        """Verify the app is a valid FastAPI application."""
        from fastapi import FastAPI
        from llm_rpg.main import app

        assert isinstance(app, FastAPI)

    def test_required_endpoints_exist(self):
        """Verify required API endpoints are registered."""
        from llm_rpg.main import app

        routes = [route.path for route in app.routes]

        # Check for required endpoints
        assert any("/saves" in route for route in routes), "Missing /saves endpoint"
        assert any("/sessions" in route for route in routes), "Missing /sessions endpoint"

    def test_app_legacy_is_not_imported_by_default(self):
        """Verify app_legacy is not imported when importing llm_rpg.main."""
        backend_dir = Path(__file__).parent.parent.parent
        os.chdir(backend_dir)

        if str(backend_dir) not in sys.path:
            sys.path.insert(0, str(backend_dir))

        # Clear any cached imports
        modules_to_clear = [k for k in sys.modules.keys() if "app_legacy" in k]
        for mod in modules_to_clear:
            del sys.modules[mod]

        # Import llm_rpg.main - this should not import app_legacy
        from llm_rpg.main import app

        # Verify app_legacy is not in sys.modules
        assert "app_legacy" not in sys.modules
        assert "backend.app_legacy" not in sys.modules

    def test_no_other_app_entrypoints_exist(self):
        """Verify no other app.py files exist that could be confused with main entrypoint."""
        backend_dir = Path(__file__).parent.parent.parent

        # Look for app.py files
        app_files = list(backend_dir.rglob("app.py"))

        # Should be empty (app_legacy.py is allowed)
        assert len(app_files) == 0, f"Found unexpected app.py files: {app_files}"

    def test_seed_config_is_importable(self):
        """Verify seed configuration is importable from llm_rpg.config."""
        from llm_rpg.config.seeds import (
            DEMO_WORLD,
            DEMO_LOCATIONS,
            DEMO_NPCS,
            build_location_states,
            build_npc_profiles,
        )

        assert DEMO_WORLD is not None
        assert len(DEMO_LOCATIONS) > 0
        assert len(DEMO_NPCS) > 0
        assert callable(build_location_states)
        assert callable(build_npc_profiles)


class TestEntrypointVerification:
    """Tests to verify the application can be started with the correct entrypoint."""

    def test_entrypoint_import_via_subprocess(self):
        """Verify the entrypoint can be imported in a clean Python process."""
        backend_dir = Path(__file__).parent.parent.parent

        # Run a subprocess that imports the app
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from llm_rpg.main import app; print('SUCCESS:', app.title)",
            ],
            cwd=backend_dir,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, f"Import failed: {result.stderr}"
        assert "SUCCESS: LLM RPG Engine" in result.stdout

    def test_no_deprecated_app_import_references(self):
        """Verify no code imports from deprecated app or app_legacy modules."""
        backend_dir = Path(__file__).parent.parent.parent

        # Search for imports of app or app_legacy (excluding app_legacy itself)
        py_files = list(backend_dir.rglob("*.py"))

        bad_imports = []
        for py_file in py_files:
            # Skip app_legacy.py and cache files
            if "app_legacy" in str(py_file) or "__pycache__" in str(py_file):
                continue

            try:
                content = py_file.read_text()
                lines = content.split("\n")
                for line in lines:
                    line = line.strip()
                    # Check for imports from standalone 'app' module (bad)
                    # But allow imports like 'from llm_rpg.main import app' (good)
                    # or 'from .main import app' (good - importing app object)
                    if line.startswith("from app ") or line.startswith("from app."):
                        bad_imports.append(f"{py_file}: {line}")
                    elif line.startswith("import app") and not line.startswith("import app_legacy"):
                        # Check if it's just 'import app' (bad) vs 'import app_something_else'
                        if line == "import app" or line.startswith("import app "):
                            bad_imports.append(f"{py_file}: {line}")
            except Exception:
                continue

        assert len(bad_imports) == 0, f"Found deprecated app imports in: {bad_imports}"

    def test_seed_data_integrity(self):
        """Verify seed data can build valid state objects."""
        from llm_rpg.config.seeds import (
            build_location_states,
            build_npc_states,
            build_npc_profiles,
        )

        # Build states
        location_states = build_location_states()
        npc_states = build_npc_states()
        npc_profiles = build_npc_profiles()

        # Verify we got valid objects
        assert len(location_states) == 9  # 9 locations in demo world
        assert len(npc_states) == 6  # 6 NPCs in demo world
        assert len(npc_profiles) == 6

        # Verify starting location
        assert "square" in location_states
        assert location_states["square"].known_to_player is True

        # Verify NPC locations
        assert npc_states["senior_sister"].location_id == "square"
        assert npc_states["elder"].location_id == "trial_hall"
