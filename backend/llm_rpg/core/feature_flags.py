import os


def story_package_instance_enabled() -> bool:
    return os.getenv("STORY_PACKAGE_INSTANCE_ENABLED", "false").lower() in ("true", "1", "yes")


def instance_snapshot_enabled() -> bool:
    return os.getenv("INSTANCE_SNAPSHOT_ENABLED", "false").lower() in ("true", "1", "yes")


def npc_memory_first_enabled() -> bool:
    return os.getenv("NPC_MEMORY_FIRST_ENABLED", "false").lower() in ("true", "1", "yes")


def story_editor_enabled() -> bool:
    return os.getenv("STORY_EDITOR_ENABLED", "false").lower() in ("true", "1", "yes")