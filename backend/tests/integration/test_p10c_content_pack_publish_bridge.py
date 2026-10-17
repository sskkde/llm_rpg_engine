import os
import uuid
from pathlib import Path

import pytest
from datetime import datetime

from sqlalchemy.orm import Session as DBSession

from llm_rpg.storage.models import (
    WorldModel,
    UserModel,
    StoryPackageVersionModel,
    FactionModel,
    PlotBeatModel,
    generate_uuid,
)
from llm_rpg.storage.repositories import (
    WorldRepository,
    UserRepository,
    StoryPackageVersionRepository,
    FactionRepository,
    PlotBeatRepository,
)
from llm_rpg.core.content_publish_service import ContentPublishError, publish_content_pack_version
from llm_rpg.core.story_package_service import (
    create_story_package_version,
    get_story_package_version,
    publish_story_package_version,
    create_version_from_content_pack,
    build_manifest_from_content_pack_definition,
    build_manifest_snapshot_from_content_pack,
    StoryPackageVersionError,
)
from llm_rpg.content.importer import ContentImportService
from llm_rpg.models.content_pack import (
    ContentPackDefinition,
    ContentPackManifest,
    ContentFileRefs,
    FactionDefinition,
    PlotBeatDefinition,
    ContentImportReport,
)


def _seed_world(db: DBSession) -> WorldModel:
    repo = WorldRepository(db)
    return repo.create({"code": f"test-world-{generate_uuid()[:8]}", "name": "Test World"})


def _seed_user(db: DBSession, is_admin: bool = True) -> UserModel:
    repo = UserRepository(db)
    return repo.create({
        "username": f"testuser-{generate_uuid()[:8]}",
        "is_admin": is_admin,
    })


def _legacy_import_pack(tmp_path: Path, pack_id: str) -> Path:
    pack_dir = tmp_path / f"legacy-{pack_id}"
    pack_dir.mkdir()
    (pack_dir / "pack.yaml").write_text(
        f"id: {pack_id}\nname: Legacy Import\nversion: 1.0.0\n",
        encoding="utf-8",
    )
    (pack_dir / "factions.yaml").write_text(
        "factions:\n  - id: imported_faction\n    name: Imported faction\n",
        encoding="utf-8",
    )
    (pack_dir / "plot_beats.yaml").write_text(
        "plot_beats:\n  - id: imported_beat\n    name: Imported beat\n    priority: 1\n",
        encoding="utf-8",
    )
    return pack_dir


_MISTY_FORD = Path(__file__).resolve().parents[3] / "content_packs" / "misty_ford"


@pytest.mark.parametrize("operation", ["import_pack", "import_pack_as_version"])
@pytest.mark.parametrize("target_kind", ["published", "draft", "legacy"])
def test_v1_import_freeze_guard_preserves_draft_and_legacy_targets(
    db_session, tmp_path, operation, target_kind
):
    target_id = f"legacy_import_{uuid.uuid4().hex}"
    pack_dir = _legacy_import_pack(tmp_path, target_id)
    if target_kind == "published":
        publish_content_pack_version(db_session, pack_dir=_MISTY_FORD, world_id=target_id)
    else:
        world = WorldModel(
            id=target_id,
            code=f"legacy-import-world-{uuid.uuid4().hex}",
            name="Legacy importer target",
        )
        db_session.add(world)
        db_session.flush()
        if target_kind == "draft":
            draft = StoryPackageVersionModel(
                story_package_id=f"draft-binding-{uuid.uuid4().hex}",
                version="0.1.0",
                status="draft",
                world_id=world.id,
            )
            db_session.add(draft)
            db_session.flush()
            world.story_package_version_id = draft.id
            db_session.flush()

    service = ContentImportService(db_session)
    if operation == "import_pack":
        import_operation = lambda: service.import_pack(pack_dir)
    else:
        import_operation = lambda: service.import_pack_as_version(pack_dir, world_id=target_id)

    if target_kind == "published":
        with pytest.raises(ContentPublishError) as raised:
            import_operation()
        assert raised.value.code == "CONTENT_FROZEN_VERSION"
        assert FactionRepository(db_session).list_by_world(target_id) == []
        assert PlotBeatRepository(db_session).list_by_world(target_id) == []
    else:
        report = import_operation()
        assert report.success is True
        assert report.factions_imported == 1
        assert report.plot_beats_imported == 1


def test_import_content_pack_cli_enforces_published_freeze(db_session, tmp_path, monkeypatch):
    target_id = f"legacy_import_{uuid.uuid4().hex}"
    publish_content_pack_version(db_session, pack_dir=_MISTY_FORD, world_id=target_id)
    pack_dir = _legacy_import_pack(tmp_path, target_id)

    from llm_rpg.scripts import import_content_pack as cli

    class NonClosingSession:
        def __getattr__(self, name):
            return getattr(db_session, name)

        def close(self):
            pass

    monkeypatch.setattr(cli, "SessionLocal", lambda: NonClosingSession())
    monkeypatch.setattr("sys.argv", ["import_content_pack.py", str(pack_dir), "--format", "json"])
    with pytest.raises(ContentPublishError) as raised:
        cli.main()
    assert raised.value.code == "CONTENT_FROZEN_VERSION"
    assert FactionRepository(db_session).list_by_world(target_id) == []
    assert PlotBeatRepository(db_session).list_by_world(target_id) == []


def test_import_content_pack_cli_preserves_legacy_world_import(db_session, tmp_path, monkeypatch):
    target_id = f"legacy_import_{uuid.uuid4().hex}"
    db_session.add(
        WorldModel(
            id=target_id,
            code=f"legacy-import-world-{uuid.uuid4().hex}",
            name="Legacy importer target",
        )
    )
    db_session.flush()
    pack_dir = _legacy_import_pack(tmp_path, target_id)

    from llm_rpg.scripts import import_content_pack as cli

    class NonClosingSession:
        def __getattr__(self, name):
            return getattr(db_session, name)

        def close(self):
            pass

    monkeypatch.setattr(cli, "SessionLocal", lambda: NonClosingSession())
    monkeypatch.setattr("sys.argv", ["import_content_pack.py", str(pack_dir), "--format", "json"])
    assert cli.main() == 0
    assert len(FactionRepository(db_session).list_by_world(target_id)) == 1
    assert len(PlotBeatRepository(db_session).list_by_world(target_id)) == 1


class TestContentPackVersionBridge:
    def test_import_pack_as_version_creates_version_row(self, db_session, tmp_path):
        pack_dir = tmp_path / "bridge_pack"
        pack_dir.mkdir()
        (pack_dir / "pack.yaml").write_text(
            "id: sp-bridge\nname: Bridge Pack\nversion: 1.0.0\n",
            encoding="utf-8",
        )
        (pack_dir / "factions.yaml").write_text(
            "factions:\n  - id: sect_azure\n    name: Azure Sect\n    visibility: public\n",
            encoding="utf-8",
        )
        (pack_dir / "plot_beats.yaml").write_text("plot_beats: []", encoding="utf-8")

        service = ContentImportService(db_session)
        report = service.import_pack_as_version(pack_dir, world_id="w-bridge-test")

        assert report.success is True
        assert report.version_id is not None
        assert report.factions_imported == 1
        assert report.manifest_json is not None
        assert report.manifest_json["pack_id"] == "sp-bridge"

        spv_repo = StoryPackageVersionRepository(db_session)
        spv = spv_repo.get_by_id(report.version_id)
        assert spv is not None
        assert spv.status == "draft"
        assert spv.source_hash is not None

    def test_import_pack_as_version_dry_run_no_version(self, db_session, tmp_path):
        pack_dir = tmp_path / "dry_pack"
        pack_dir.mkdir()
        (pack_dir / "pack.yaml").write_text(
            "id: sp-dry\nname: Dry Pack\nversion: 1.0.0\n",
            encoding="utf-8",
        )
        (pack_dir / "factions.yaml").write_text("factions: []", encoding="utf-8")

        service = ContentImportService(db_session)
        report = service.import_pack_as_version(pack_dir, dry_run=True)

        assert report.success is True
        assert report.version_id is None
        assert report.dry_run is True

    def test_import_pack_as_version_failed_import_no_version(self, db_session, tmp_path):
        bad_dir = tmp_path / "bad_pack"
        bad_dir.mkdir()

        service = ContentImportService(db_session)
        report = service.import_pack_as_version(bad_dir)

        assert report.success is False
        assert report.version_id is None

    def test_old_import_pack_unchanged(self, db_session, tmp_path):
        pack_dir = tmp_path / "old_pack"
        pack_dir.mkdir()
        (pack_dir / "pack.yaml").write_text(
            "id: sp-old\nname: Old Pack\nversion: 1.0.0\n",
            encoding="utf-8",
        )
        (pack_dir / "factions.yaml").write_text(
            "factions:\n  - id: sect_old\n    name: Old Sect\n    visibility: public\n",
            encoding="utf-8",
        )
        (pack_dir / "plot_beats.yaml").write_text(
            "plot_beats:\n  - id: pb_old\n    name: Old Beat\n    priority: 5\n",
            encoding="utf-8",
        )

        service = ContentImportService(db_session)
        report = service.import_pack(pack_dir)

        assert report.success is True
        assert report.factions_imported == 1
        assert report.plot_beats_imported == 1
        assert report.pack_id == "sp-old"
        assert not hasattr(report, "version_id") or report.version_id is None

    def test_existing_factions_unchanged_after_version_bridge(self, db_session, tmp_path):
        world = _seed_world(db_session)
        faction_repo = FactionRepository(db_session)

        faction_repo.create({
            "logical_id": "pre_exist",
            "world_id": world.id,
            "name": "Pre-existing Faction",
        })

        pack_dir = tmp_path / "faction_pack"
        pack_dir.mkdir()
        (pack_dir / "pack.yaml").write_text(
            "id: sp-faction\nname: Faction Pack\nversion: 1.0.0\n",
            encoding="utf-8",
        )
        (pack_dir / "factions.yaml").write_text(
            "factions:\n  - id: new_faction\n    name: New Faction\n    visibility: public\n",
            encoding="utf-8",
        )
        (pack_dir / "plot_beats.yaml").write_text("plot_beats: []", encoding="utf-8")

        service = ContentImportService(db_session)
        report = service.import_pack_as_version(pack_dir, world_id=world.id)

        assert report.success is True
        assert report.factions_imported == 1

        factions = faction_repo.list_by_world(world.id)
        assert len(factions) == 1

    def test_version_manifest_captures_entity_counts(self, db_session, tmp_path):
        pack_dir = tmp_path / "count_pack"
        pack_dir.mkdir()
        (pack_dir / "pack.yaml").write_text(
            "id: sp-count\nname: Count Pack\nversion: 1.0.0\n",
            encoding="utf-8",
        )
        (pack_dir / "factions.yaml").write_text(
            "factions:\n  - id: f1\n    name: Faction 1\n    visibility: public\n  - id: f2\n    name: Faction 2\n    visibility: hidden\n",
            encoding="utf-8",
        )
        (pack_dir / "plot_beats.yaml").write_text(
            "plot_beats:\n  - id: pb1\n    name: Beat 1\n    priority: 1\n  - id: pb2\n    name: Beat 2\n    priority: 2\n  - id: pb3\n    name: Beat 3\n    priority: 3\n",
            encoding="utf-8",
        )

        service = ContentImportService(db_session)
        report = service.import_pack_as_version(pack_dir)

        assert report.success is True
        assert report.manifest_json["entity_counts"]["factions"] == 2
        assert report.manifest_json["entity_counts"]["plot_beats"] == 3

    def test_duplicate_version_creates_warning(self, db_session, tmp_path):
        pack_dir = tmp_path / "dup_pack"
        pack_dir.mkdir()
        (pack_dir / "pack.yaml").write_text(
            "id: sp-dup-bridge\nname: Dup Bridge\nversion: 1.0.0\n",
            encoding="utf-8",
        )
        (pack_dir / "factions.yaml").write_text("factions: []", encoding="utf-8")

        service = ContentImportService(db_session)

        report1 = service.import_pack_as_version(pack_dir)
        assert report1.success is True
        assert report1.version_id is not None

        report2 = service.import_pack_as_version(pack_dir)
        assert report2.success is True
        assert len([w for w in report2.warnings if "Version creation skipped" in w]) == 1


class TestContentPackValidateAndImportContract:
    def test_validate_endpoint_unchanged(self, client, db_session):
        world = _seed_world(db_session)
        user = _seed_user(db_session, is_admin=True)

        from passlib.context import CryptContext
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        user_repo = UserRepository(db_session)
        user_repo.create({
            "username": f"admin-validate-{generate_uuid()[:8]}",
            "password_hash": pwd_context.hash("Pass123!"),
            "is_admin": True,
        })
        db_session.commit()

        login_resp = client.post("/auth/login", json={
            "username": user_repo.get_all()[-1].username,
            "password": "Pass123!",
        })
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.post(
            "/admin/content-packs/validate",
            json={"path": "content_packs/nonexistent"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["is_valid"] is False

    def test_import_endpoint_response_contract_unchanged(self, client, db_session, tmp_path):
        user_repo = UserRepository(db_session)
        from passlib.context import CryptContext
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        admin = user_repo.create({
            "username": f"admin-import-{generate_uuid()[:8]}",
            "password_hash": pwd_context.hash("Pass123!"),
            "is_admin": True,
        })
        db_session.commit()

        login_resp = client.post("/auth/login", json={
            "username": admin.username,
            "password": "Pass123!",
        })
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.post(
            "/admin/content-packs/import",
            json={"path": "content_packs/nonexistent"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "success" in data
        assert "imported_count" in data
        assert "factions_imported" in data
        assert "plot_beats_imported" in data
        assert "errors" in data
        assert "warnings" in data
        assert "dry_run" in data


class TestBuildManifestFromDefinition:
    def test_file_refs_with_missing_fields(self):
        pack = ContentPackDefinition(
            manifest=ContentPackManifest(id="p-refs", name="Refs", version="1.0.0"),
            file_refs=ContentFileRefs(factions=["factions.yaml"]),
        )
        manifest = build_manifest_from_content_pack_definition(pack)
        assert manifest["source_files"]["factions"] == ["factions.yaml"]
        assert "npcs" not in manifest["source_files"]
        assert "locations" not in manifest["source_files"]

    def test_no_file_refs(self):
        pack = ContentPackDefinition(
            manifest=ContentPackManifest(id="p-norefs", name="NoRefs", version="1.0.0"),
        )
        manifest = build_manifest_from_content_pack_definition(pack)
        assert "source_files" not in manifest

    def test_empty_file_refs(self):
        pack = ContentPackDefinition(
            manifest=ContentPackManifest(id="p-empty", name="Empty", version="1.0.0"),
            file_refs=ContentFileRefs(),
        )
        manifest = build_manifest_from_content_pack_definition(pack)
        assert "source_files" not in manifest