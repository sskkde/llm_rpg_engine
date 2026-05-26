import hashlib
import pytest
from pathlib import Path

from llm_rpg.models.content_pack import (
    ContentPackDefinition,
    ContentPackManifest,
    ContentFileRefs,
    FactionDefinition,
    PlotBeatDefinition,
)
from llm_rpg.core.story_package_service import (
    build_manifest_snapshot_from_content_pack,
    build_manifest_from_content_pack_definition,
    compute_source_hash_from_pack_dir,
    create_story_package_version,
    create_version_from_content_pack,
    StoryPackageVersionError,
)
from llm_rpg.storage.repositories import StoryPackageVersionRepository


class TestBuildManifestSnapshotFromContentPack:
    def test_minimal_manifest(self):
        manifest = build_manifest_snapshot_from_content_pack(
            pack_id="pack-001",
            pack_name="Test Pack",
            pack_version="1.0.0",
        )
        assert manifest["pack_id"] == "pack-001"
        assert manifest["pack_name"] == "Test Pack"
        assert manifest["pack_version"] == "1.0.0"
        assert "source_files" not in manifest
        assert "extra_metadata" not in manifest

    def test_manifest_with_source_files(self):
        manifest = build_manifest_snapshot_from_content_pack(
            pack_id="pack-002",
            pack_name="Test Pack 2",
            pack_version="2.0.0",
            source_files=["factions.yaml", "npcs.yaml"],
        )
        assert manifest["source_files"] == ["factions.yaml", "npcs.yaml"]

    def test_manifest_with_extra_metadata(self):
        manifest = build_manifest_snapshot_from_content_pack(
            pack_id="pack-003",
            pack_name="Test Pack 3",
            pack_version="3.0.0",
            extra_metadata={"genre": "xianxia", "author": "admin"},
        )
        assert manifest["extra_metadata"] == {"genre": "xianxia", "author": "admin"}


class TestBuildManifestFromContentPackDefinition:
    def test_from_minimal_definition(self):
        pack = ContentPackDefinition(
            manifest=ContentPackManifest(id="p1", name="Pack 1", version="1.0.0"),
        )
        manifest = build_manifest_from_content_pack_definition(pack)
        assert manifest["pack_id"] == "p1"
        assert manifest["pack_name"] == "Pack 1"
        assert manifest["pack_version"] == "1.0.0"
        assert manifest["entity_counts"]["factions"] == 0
        assert manifest["entity_counts"]["plot_beats"] == 0

    def test_from_definition_with_entities(self):
        pack = ContentPackDefinition(
            manifest=ContentPackManifest(id="p2", name="Pack 2", version="2.0.0"),
            factions=[
                FactionDefinition(id="f1", name="Sect", world_id="w1"),
                FactionDefinition(id="f2", name="Clan", world_id="w1"),
            ],
            plot_beats=[
                PlotBeatDefinition(id="pb1", title="Trigger", world_id="w1"),
            ],
            file_refs=ContentFileRefs(
                factions=["factions.yaml"],
                npcs=["npcs.yaml"],
            ),
            metadata={"genre": "xianxia"},
        )
        manifest = build_manifest_from_content_pack_definition(pack)
        assert manifest["entity_counts"]["factions"] == 2
        assert manifest["entity_counts"]["plot_beats"] == 1
        assert manifest["source_files"]["factions"] == ["factions.yaml"]
        assert manifest["source_files"]["npcs"] == ["npcs.yaml"]
        assert manifest["pack_metadata"]["genre"] == "xianxia"

    def test_from_definition_with_source_hash(self):
        pack = ContentPackDefinition(
            manifest=ContentPackManifest(id="p3", name="Pack 3", version="3.0.0"),
        )
        manifest = build_manifest_from_content_pack_definition(
            pack, source_hash="abc123",
        )
        assert manifest["source_hash"] == "abc123"


class TestComputeSourceHashFromPackDir:
    def test_deterministic_hash(self, tmp_path):
        pack_dir = tmp_path / "test_pack"
        pack_dir.mkdir()
        (pack_dir / "pack.yaml").write_text("id: test\nname: Test", encoding="utf-8")
        (pack_dir / "factions.yaml").write_text("factions: []", encoding="utf-8")

        h1 = compute_source_hash_from_pack_dir(pack_dir)
        h2 = compute_source_hash_from_pack_dir(pack_dir)
        assert h1 == h2
        assert len(h1) == 64

    def test_different_content_different_hash(self, tmp_path):
        pack_dir1 = tmp_path / "pack1"
        pack_dir1.mkdir()
        (pack_dir1 / "pack.yaml").write_text("id: v1", encoding="utf-8")

        pack_dir2 = tmp_path / "pack2"
        pack_dir2.mkdir()
        (pack_dir2 / "pack.yaml").write_text("id: v2", encoding="utf-8")

        h1 = compute_source_hash_from_pack_dir(pack_dir1)
        h2 = compute_source_hash_from_pack_dir(pack_dir2)
        assert h1 != h2

    def test_empty_dir_hash(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        h = compute_source_hash_from_pack_dir(empty_dir)
        assert len(h) == 64

    def test_sorted_file_order(self, tmp_path):
        pack_dir = tmp_path / "sort_pack"
        pack_dir.mkdir()
        (pack_dir / "z.yaml").write_text("z", encoding="utf-8")
        (pack_dir / "a.yaml").write_text("a", encoding="utf-8")

        expected = hashlib.sha256("a".encode("utf-8") + "z".encode("utf-8")).hexdigest()
        h = compute_source_hash_from_pack_dir(pack_dir)
        assert h == expected


class TestCreateVersionFromContentPack:
    def test_creates_draft_version(self, db_session, tmp_path):
        pack_dir = tmp_path / "valid_pack"
        pack_dir.mkdir()
        (pack_dir / "pack.yaml").write_text(
            "id: sp-test\nname: Test SP\nversion: 1.0.0\n",
            encoding="utf-8",
        )
        (pack_dir / "factions.yaml").write_text("factions: []", encoding="utf-8")
        (pack_dir / "plot_beats.yaml").write_text("plot_beats: []", encoding="utf-8")

        spv = create_version_from_content_pack(db_session, pack_dir=pack_dir)
        assert spv.id is not None
        assert spv.story_package_id == "sp-test"
        assert spv.version == "1.0.0"
        assert spv.status == "draft"
        assert spv.manifest_json is not None
        assert spv.manifest_json["pack_id"] == "sp-test"
        assert spv.source_hash is not None
        assert len(spv.source_hash) == 64

    def test_duplicate_raises(self, db_session, tmp_path):
        pack_dir = tmp_path / "dup_pack"
        pack_dir.mkdir()
        (pack_dir / "pack.yaml").write_text(
            "id: sp-dup\nname: Dup SP\nversion: 1.0.0\n",
            encoding="utf-8",
        )
        (pack_dir / "factions.yaml").write_text("factions: []", encoding="utf-8")

        create_version_from_content_pack(db_session, pack_dir=pack_dir)
        with pytest.raises(StoryPackageVersionError, match="already exists"):
            create_version_from_content_pack(db_session, pack_dir=pack_dir)

    def test_invalid_pack_dir_raises(self, db_session, tmp_path):
        empty_dir = tmp_path / "bad_pack"
        empty_dir.mkdir()
        with pytest.raises(StoryPackageVersionError, match="Failed to load"):
            create_version_from_content_pack(db_session, pack_dir=empty_dir)


class TestManifestIntegrity:
    def test_manifest_snapshot_roundtrip(self):
        manifest = build_manifest_snapshot_from_content_pack(
            pack_id="meta-pack",
            pack_name="Meta Pack",
            pack_version="2.0.0",
            source_files=["factions.yaml"],
            extra_metadata={"genre": "xianxia", "author": "admin"},
        )
        assert manifest["pack_id"] == "meta-pack"
        assert manifest["source_files"] == ["factions.yaml"]
        assert manifest["extra_metadata"]["genre"] == "xianxia"
        assert manifest["extra_metadata"]["author"] == "admin"

    def test_definition_manifest_roundtrip(self):
        pack = ContentPackDefinition(
            manifest=ContentPackManifest(id="p-def", name="Def", version="1.0.0"),
            metadata={"genre": "fantasy", "tags": ["rpg"]},
            file_refs=ContentFileRefs(quests=["quests.yaml"]),
        )
        manifest = build_manifest_from_content_pack_definition(pack)
        assert manifest["pack_id"] == "p-def"
        assert manifest["pack_metadata"]["genre"] == "fantasy"
        assert manifest["source_files"]["quests"] == ["quests.yaml"]