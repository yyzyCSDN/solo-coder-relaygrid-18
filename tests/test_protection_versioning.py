from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from relaygrid.protection.versioning import (
    ApprovalChain,
    ArtifactNotFoundError,
    CalculationCase,
    DeviceTemplate,
    DuplicateApprovalError,
    DuplicateArtifactError,
    DuplicateVersionError,
    InvalidFieldSettingError,
    InvalidVersionStateError,
    ProtectionSettingRepository,
    SnapshotError,
    VersionStatus,
    canonical_json,
)


def build_repository() -> ProtectionSettingRepository:
    repo = ProtectionSettingRepository()
    repo.add_approval_chain(ApprovalChain("standard", "Standard", ["engineer", "engineer_manager"]))
    repo.add_device_template(
        DeviceTemplate(
            "recloser-a",
            "recloser",
            manufacturer="GridCo",
            model="R1",
            parameters={"pickup_a": 300, "curve": "standard"},
        )
    )
    repo.add_calculation_case(
        CalculationCase(
            "fault-3ph",
            "Three-phase fault",
            inputs={"fault_a": 5000},
            results={"operate_s": 0.12},
        )
    )
    return repo


def approve_and_publish(repo: ProtectionSettingRepository, version_id: str):
    repo.submit_for_approval(version_id, "planner")
    repo.approve(version_id, "engineer", "ok")
    repo.approve(version_id, "engineer_manager", "approved")
    return repo.publish(version_id, "owner")


def test_draft_approval_publication_and_field_traceability():
    repo = build_repository()
    version = repo.create_draft(
        "feeder-12",
        "standard",
        title="Feeder 12 study",
        template_ids=["recloser-a"],
        case_ids=["fault-3ph"],
        settings={"device-1": {"pickup_a": 320, "curve": "standard"}},
        actor="planner",
    )

    published = approve_and_publish(repo, version.version_id)

    assert published.status is VersionStatus.PUBLISHED
    assert published.revision == 1
    assert published.content_hash
    assert len(published.approvals) == 2

    field_setting = repo.register_field_setting(
        "device-1",
        published.version_id,
        {"pickup_a": 320, "curve": "standard"},
        actor="field-tech",
    )
    trace = repo.trace_field_setting(field_setting.field_setting_id)

    assert trace["field_setting"]["version_id"] == published.version_id
    assert trace["field_setting"]["content_hash"] == published.content_hash
    assert trace["version"]["status"] == "published"


def test_released_version_and_embedded_artifacts_are_immutable():
    repo = build_repository()
    version = repo.create_draft(
        "feeder-12",
        "standard",
        template_ids=["recloser-a"],
        settings={"device-1": {"pickup_a": 320}},
    )
    published = approve_and_publish(repo, version.version_id)

    with pytest.raises(InvalidVersionStateError):
        repo.update_draft(published.version_id, settings={"device-1": {"pickup_a": 400}})
    with pytest.raises(InvalidVersionStateError):
        repo.withdraw(published.version_id)
    with pytest.raises(FrozenInstanceError):
        published.title = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        published.settings["device-1"] = {"pickup_a": 400}

    repo.update_device_template(
        DeviceTemplate(
            "recloser-a",
            "recloser",
            manufacturer="GridCo",
            model="R2",
            parameters={"pickup_a": 400},
        )
    )

    rebuilt_version = repo.get_version(published.version_id)
    assert rebuilt_version.templates[0].model == "R1"
    assert rebuilt_version.templates[0].parameters["pickup_a"] == 300


def test_parallel_drafts_have_independent_lifecycles_and_ordered_revisions():
    repo = build_repository()
    first = repo.create_draft("feeder-12", "standard", title="first")
    second = repo.create_draft("feeder-12", "standard", title="second")

    assert first.version_id != second.version_id
    assert len(repo.list_versions("feeder-12", VersionStatus.DRAFT)) == 2

    first_published = approve_and_publish(repo, first.version_id)
    second_published = approve_and_publish(repo, second.version_id)

    assert first_published.revision == 1
    assert second_published.revision == 2
    assert repo.latest_published_version("feeder-12").version_id == second.version_id


def test_withdrawn_draft_cannot_continue_approval():
    repo = build_repository()
    version = repo.create_draft("feeder-12", "standard")
    withdrawn = repo.withdraw(version.version_id, "planner", "superseded")

    assert withdrawn.status is VersionStatus.WITHDRAWN
    with pytest.raises(InvalidVersionStateError):
        repo.submit_for_approval(version.version_id)
    with pytest.raises(InvalidVersionStateError):
        repo.publish(version.version_id)


def test_duplicate_approval_is_rejected_deterministically():
    repo = build_repository()
    version = repo.create_draft("feeder-12", "standard")
    repo.submit_for_approval(version.version_id)
    repo.approve(version.version_id, "engineer")

    with pytest.raises(DuplicateApprovalError):
        repo.approve(version.version_id, "engineer")
    repo.approve(version.version_id, "engineer_manager", "complete approval")
    with pytest.raises(DuplicateApprovalError):
        repo.approve(version.version_id, "engineer")
    with pytest.raises(DuplicateApprovalError):
        repo.approve(version.version_id, "engineer_manager")

    assert len(repo.get_version(version.version_id).approvals) == 2


def test_field_values_must_match_approved_study():
    repo = build_repository()
    version = repo.create_draft(
        "feeder-12",
        "standard",
        settings={"device-1": {"pickup_a": 320}},
    )

    with pytest.raises(InvalidVersionStateError):
        repo.register_field_setting("device-1", version.version_id, {"pickup_a": 320})

    published = approve_and_publish(repo, version.version_id)

    with pytest.raises(InvalidFieldSettingError):
        repo.register_field_setting("device-1", published.version_id, {"pickup_a": 400})
    with pytest.raises(InvalidFieldSettingError):
        repo.register_field_setting("missing-device", published.version_id, {})


def test_duplicate_identifiers_are_rejected():
    repo = build_repository()
    version = repo.create_draft("feeder-12", "standard", version_id="study-v1")

    with pytest.raises(DuplicateVersionError):
        repo.create_draft("feeder-12", "standard", version_id="study-v1")
    with pytest.raises(DuplicateArtifactError):
        repo.add_device_template(DeviceTemplate("recloser-a", "recloser"))
    with pytest.raises(DuplicateArtifactError):
        repo.add_calculation_case(CalculationCase("fault-3ph", "duplicate"))
    with pytest.raises(DuplicateArtifactError):
        repo.add_approval_chain(ApprovalChain("standard", "dup", ["x"]))

    assert version.version_id == "study-v1"


def test_snapshot_round_trip_is_canonical_and_complete():
    repo = build_repository()
    first = repo.create_draft(
        "feeder-12",
        "standard",
        title="Baseline",
        template_ids=["recloser-a"],
        case_ids=["fault-3ph"],
        settings={"device-1": {"pickup_a": 320}},
    )
    approve_and_publish(repo, first.version_id)
    field_setting = repo.register_field_setting(
        "device-1", first.version_id, {"pickup_a": 320}
    )
    repo.create_draft("feeder-12", "standard", title="Parallel work")

    payload = repo.export_json()
    assert payload == canonical_json(repo.export_snapshot())
    restored = ProtectionSettingRepository.from_json(payload)

    assert restored.export_json() == payload
    assert restored.get_version(first.version_id).templates[0].to_dict() == (
        repo.get_version(first.version_id).templates[0].to_dict()
    )
    assert restored.get_field_setting(field_setting.field_setting_id).to_dict() == (
        repo.get_field_setting(field_setting.field_setting_id).to_dict()
    )
    assert len(restored.list_versions(status=VersionStatus.DRAFT)) == 1


def test_single_version_export_rebuilds_approved_research():
    repo = build_repository()
    version = repo.create_draft(
        "feeder-12",
        "standard",
        title="Rebuildable",
        template_ids=["recloser-a"],
        case_ids=["fault-3ph"],
        settings={"device-1": {"pickup_a": 320}},
    )
    published = approve_and_publish(repo, version.version_id)
    field_setting = repo.register_field_setting(
        "device-1", published.version_id, {"pickup_a": 320}
    )
    exported = repo.export_version(published.version_id)

    restored = ProtectionSettingRepository.from_version_export(exported)
    rebuilt = restored.get_version(published.version_id)

    assert rebuilt.to_dict() == published.to_dict()
    assert restored.get_device_template("recloser-a").model == "R1"
    assert restored.get_calculation_case("fault-3ph").results == {"operate_s": 0.12}
    assert restored.get_approval_chain("standard").approvers == (
        "engineer",
        "engineer_manager",
    )
    assert restored.get_field_setting(field_setting.field_setting_id).version_id == published.version_id


def test_catalog_changes_after_draft_creation_do_not_change_review_chain():
    repo = build_repository()
    version = repo.create_draft("feeder-12", "standard")

    with pytest.raises(ArtifactNotFoundError):
        repo.update_approval_chain(ApprovalChain("missing", "Missing", ["x"]))
    repo.update_approval_chain(ApprovalChain("standard", "Changed", ["other"]))

    submitted = repo.submit_for_approval(version.version_id)
    assert submitted.chain.approvers == ("engineer", "engineer_manager")
    with pytest.raises(Exception):
        repo.approve(version.version_id, "other")


def test_field_setting_re_registration_is_rejected_and_snapshots_cannot_duplicate_it():
    repo = build_repository()
    version = repo.create_draft(
        "feeder-12",
        "standard",
        settings={"device-1": {"pickup_a": 320}},
    )
    published = approve_and_publish(repo, version.version_id)
    repo.register_field_setting("device-1", published.version_id, {"pickup_a": 320})

    with pytest.raises(DuplicateArtifactError):
        repo.register_field_setting("device-1", published.version_id, {"pickup_a": 320})

    snapshot = repo.export_snapshot()
    snapshot["field_settings"].append(dict(snapshot["field_settings"][0]))

    with pytest.raises(SnapshotError):
        ProtectionSettingRepository.from_snapshot(snapshot)


def test_corrupt_snapshot_hash_is_rejected():
    repo = build_repository()
    version = repo.create_draft(
        "feeder-12",
        "standard",
        settings={"device-1": {"pickup_a": 320}},
    )
    approve_and_publish(repo, version.version_id)
    snapshot = repo.export_snapshot()
    snapshot["versions"][0]["settings"]["device-1"]["pickup_a"] = 999

    with pytest.raises(SnapshotError):
        ProtectionSettingRepository.from_snapshot(snapshot)
