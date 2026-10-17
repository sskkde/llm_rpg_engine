"""Safe, single-capture YAML loader for content pack schema v2."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

import yaml

from llm_rpg.models.content_v2 import (
    ContentPackV2,
    ContentV2Error,
    LocationsFile,
    PACK_SCHEMA_VERSION,
)

_REQUIRED_FILES = ("pack.yaml", "world.yaml", "locations.yaml", "initial_state.yaml")
_SECTION_FILES = {
    "characters.yaml": "characters",
    "items.yaml": "items",
    "rules.yaml": "rules",
    "schedules.yaml": "schedules",
    "knowledge.yaml": "knowledge_rules",
    "quests.yaml": "quests",
    "plot_beats.yaml": "plot_beats",
    "factions.yaml": "factions",
}
_PYTHON_TAG_PREFIX = "tag:yaml.org,2002:python/"


class _DuplicateKeyError(yaml.YAMLError):
    def __init__(self, key: Any, mark: Any) -> None:
        self.key = key
        self.mark = mark
        super().__init__(f"duplicate YAML key {key!r}")


class _ContentSafeLoader(yaml.SafeLoader):
    """SafeLoader variant that rejects duplicate mapping keys."""

    yaml_constructors = {
        tag: constructor
        for tag, constructor in yaml.SafeLoader.yaml_constructors.items()
        if not (isinstance(tag, str) and tag.startswith(_PYTHON_TAG_PREFIX))
    }
    yaml_multi_constructors = {
        tag: constructor
        for tag, constructor in yaml.SafeLoader.yaml_multi_constructors.items()
        if not (isinstance(tag, str) and tag.startswith(_PYTHON_TAG_PREFIX))
    }

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        if not isinstance(node, yaml.MappingNode):
            raise yaml.constructor.ConstructorError(None, None, "expected a mapping node", node.start_mark)
        self.flatten_mapping(node)
        seen: dict[Any, Any] = {}
        for key_node, _value_node in node.value:
            key = self.construct_object(key_node, deep=True)
            try:
                duplicate = key in seen
            except TypeError:
                # Let SafeLoader raise its normal, safe-construction error for
                # a non-hashable YAML mapping key.
                continue
            if duplicate:
                raise _DuplicateKeyError(key, key_node.start_mark)
            seen[key] = key_node.start_mark
        return super().construct_mapping(node, deep=deep)


def _ensure_acyclic_and_finite(value: Any, filename: str) -> None:
    active: set[int] = set()

    def visit(node: Any, path: str) -> None:
        if isinstance(node, float) and not math.isfinite(node):
            raise ContentV2Error(
                "CONTENT_NON_FINITE_NUMBER",
                path,
                "YAML numeric values must be finite",
            )
        if not isinstance(node, (dict, list, tuple)):
            return
        identity = id(node)
        if identity in active:
            raise ContentV2Error(
                "CONTENT_UNSUPPORTED_FEATURE",
                path,
                "recursive YAML aliases are not supported",
            )
        active.add(identity)
        try:
            if isinstance(node, dict):
                for key, child in node.items():
                    visit(key, f"{path}.{key}" if path else str(key))
                    visit(child, f"{path}.{key}" if path else str(key))
            else:
                for index, child in enumerate(node):
                    visit(child, f"{path}.{index}" if path else str(index))
        finally:
            active.remove(identity)

    visit(value, filename)


def capture_pack_bytes(pack_dir: Path) -> dict[str, bytes]:
    """Capture all top-level YAML files once, rejecting escaping symlinks."""
    root = Path(pack_dir).resolve()
    if not root.is_dir():
        raise ContentV2Error("CONTENT_DANGLING_REF", str(pack_dir), "content pack directory does not exist")

    captured: dict[str, bytes] = {}
    try:
        candidates = sorted(root.glob("*.yaml"), key=lambda path: path.name)
        for candidate in candidates:
            try:
                resolved = candidate.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise ContentV2Error(
                    "CONTENT_PATH_ESCAPE",
                    candidate.name,
                    f"cannot safely resolve YAML file: {exc}",
                ) from exc
            if not resolved.is_relative_to(root):
                raise ContentV2Error(
                    "CONTENT_PATH_ESCAPE",
                    candidate.name,
                    "YAML file resolves outside the content pack directory",
                )
            if not resolved.is_file():
                raise ContentV2Error(
                    "CONTENT_TYPE_ERROR",
                    candidate.name,
                    "top-level .yaml entry must be a regular file",
                )
            try:
                captured[candidate.name] = resolved.read_bytes()
            except OSError as exc:
                raise ContentV2Error("CONTENT_TYPE_ERROR", candidate.name, f"cannot read YAML file: {exc}") from exc
    except OSError as exc:
        raise ContentV2Error("CONTENT_TYPE_ERROR", str(pack_dir), f"cannot enumerate content pack: {exc}") from exc
    return captured


def compute_source_hash(files: dict[str, bytes]) -> str:
    """Match the v1 sorted-filename, concatenated-text SHA-256 fingerprint."""
    try:
        combined = "".join(files[name].decode("utf-8") for name in sorted(files))
    except UnicodeDecodeError as exc:
        raise ContentV2Error("CONTENT_TYPE_ERROR", str(exc), "YAML files must be UTF-8") from exc
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def _parse_yaml(filename: str, content: bytes) -> Any:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContentV2Error("CONTENT_TYPE_ERROR", filename, "YAML files must be UTF-8") from exc

    loader = _ContentSafeLoader(text)
    try:
        data = loader.get_single_data()
    except _DuplicateKeyError as exc:
        line = getattr(exc.mark, "line", 0) + 1
        raise ContentV2Error(
            "CONTENT_DUPLICATE_KEY",
            f"{filename}:{line}",
            str(exc),
        ) from exc
    except yaml.YAMLError as exc:
        message = str(exc)
        if _PYTHON_TAG_PREFIX in message or "python/" in message:
            code = "CONTENT_UNSUPPORTED_FEATURE"
            message = f"Python YAML tags are forbidden: {message}"
        else:
            code = "CONTENT_TYPE_ERROR"
        raise ContentV2Error(code, filename, message) from exc
    except (RecursionError, ValueError) as exc:
        raise ContentV2Error("CONTENT_UNSUPPORTED_FEATURE", filename, f"unsupported YAML alias structure: {exc}") from exc
    finally:
        loader.dispose()

    _ensure_acyclic_and_finite(data, filename)
    return data


def _single_section(data: Any, key: str, filename: str) -> Any:
    if isinstance(data, dict) and key in data:
        extras = set(data) - {key}
        if extras:
            field = sorted(str(extra) for extra in extras)[0]
            raise ContentV2Error("CONTENT_UNKNOWN_FIELD", f"{filename}.{field}", f"unknown field {field!r}")
        return data[key]
    return data


def _collection_section(data: Any, section: str, filename: str) -> list[Any]:
    if isinstance(data, dict):
        extras = set(data) - {section}
        if extras:
            field = sorted(str(extra) for extra in extras)[0]
            raise ContentV2Error("CONTENT_UNKNOWN_FIELD", f"{filename}.{field}", f"unknown field {field!r}")
        if section not in data:
            raise ContentV2Error("CONTENT_TYPE_ERROR", filename, f"expected {section!r} collection")
        return data[section]
    return data


def _parse_collection_files(parsed: dict[str, Any], section_values: dict[str, Any]) -> None:
    for filename, section in _SECTION_FILES.items():
        if filename not in parsed:
            continue
        section_values[section] = _collection_section(parsed[filename], section, filename)


def load_pack_v2(pack_dir: Path) -> ContentPackV2:
    """Load a v2 pack from one captured set of safe YAML bytes."""
    files = capture_pack_bytes(pack_dir)
    for filename in _REQUIRED_FILES:
        if filename not in files:
            raise ContentV2Error(
                "CONTENT_DANGLING_REF",
                filename,
                f"required content pack file {filename!r} is missing",
            )

    parsed: dict[str, Any] = {}
    known_files = set(_REQUIRED_FILES) | set(_SECTION_FILES) | {"goals.yaml", "prompts.yaml"}
    for filename in sorted(known_files & files.keys()):
        parsed[filename] = _parse_yaml(filename, files[filename])

    manifest_data = parsed["pack.yaml"]
    if not isinstance(manifest_data, dict) or "schema_version" not in manifest_data:
        raise ContentV2Error(
            "CONTENT_PACK_SCHEMA_UNSUPPORTED",
            "pack.yaml.schema_version",
            "pack.yaml must declare schema_version: 2",
        )
    schema_version = manifest_data["schema_version"]
    if type(schema_version) is not int or schema_version != PACK_SCHEMA_VERSION:
        raise ContentV2Error(
            "CONTENT_PACK_SCHEMA_UNSUPPORTED",
            "pack.yaml.schema_version",
            f"unsupported content pack schema version {schema_version!r}",
        )

    world_data = _single_section(parsed["world.yaml"], "world", "world.yaml")
    locations_file = LocationsFile.model_validate(parsed["locations.yaml"])
    initial_state_data = _single_section(parsed["initial_state.yaml"], "initial_state", "initial_state.yaml")

    assembled: dict[str, Any] = {
        "manifest": manifest_data,
        "world": world_data,
        "locations": locations_file.locations,
        "routes": locations_file.routes,
        "initial_state": initial_state_data,
    }
    section_values: dict[str, Any] = {}
    _parse_collection_files(parsed, section_values)

    # goals.yaml contains two sibling collections; preserve the source layout
    # while applying a closed-key check to its wrapper.
    if "goals.yaml" in parsed:
        goals_data = parsed["goals.yaml"]
        if isinstance(goals_data, dict):
            unknown = set(goals_data) - {"goals", "recipes"}
            if unknown:
                field = sorted(str(value) for value in unknown)[0]
                raise ContentV2Error("CONTENT_UNKNOWN_FIELD", f"goals.yaml.{field}", f"unknown field {field!r}")
            section_values["goals"] = goals_data.get("goals", [])
            section_values["recipes"] = goals_data.get("recipes", [])
        elif isinstance(goals_data, list):
            # A bare list remains a compact goals-only representation.
            section_values["goals"] = goals_data
        else:
            raise ContentV2Error("CONTENT_TYPE_ERROR", "goals.yaml", "expected a goals/recipes mapping")

    assembled.update(section_values)
    # Parse prompts.yaml for safety (duplicate keys, aliases, finite numbers),
    # but it is intentionally not a runtime section of ContentPackV2.
    # It is presentation-only and has no frozen model in the W1 contract.

    return ContentPackV2.model_validate(assembled)
