"""Tests for the protection setting version library.

These tests encode the deterministic rules of the library:

* released versions are immutable and content-hashed;
* field settings are traceable only to released versions;
* parallel drafts, withdrawals and duplicate approvals have fixed outcomes;
* exports (snapshots and dossiers) reconstruct verbatim and detect tampering.
"""
from __future__ import annotations

import json

import pytest

from relaygrid.protection import (
    CaseState,
    SettingItem,
    SettingVersionLibrary,
)
from relaygrid.protection.version_library import (
    DOSSIER_FORMAT,
    SNAPSHOT_FORMAT,
    SettingVersion,
)


def settings(**values) -> tuple[SettingItem, ...]:
    return tuple(SettingItem(k, float(v), "A") for k, v in values.items())


def make_library() -> SettingVersionLibrary:
    lib = SettingVersionLibrary()
    lib.define_template("REL_600", "Feeder relay", "relay",
                        settings(pickup=480, tms=0.3), now=0.0)
    lib.define_chain("STD", "Standard approval",
                     ("lead", "senior", "manager"), now=0.0)
    return lib


def approve_and_release(lib: SettingVersionLibrary, case_id: str,
                        now: float = 100.0) -> SettingVersion:
    lib.submit_case(case_id, "STD", now=now + 1)
    lib.approve(case_id, "lead", now + 2)
    lib.approve(case_id, "senior", now + 3)
    lib.approve(case_id, "manager", now + 4)
    return lib.release(case_id, now + 5)


def run_to_release(lib: SettingVersionLibrary, case_id: str, device_id: str,
                   now: float = 100.0) -> SettingVersion:
    lib.create_case(case_id, device_id, "REL_600", submitter="engineer",
                    now=now)
    return approve_and_release(lib, case_id, now)


# -- templates / chains -----------------------------------------------------

def test_template_revisions_are_immutable_and_pinned():
    lib = make_library()
    rev1 = lib.get_template("REL_600")
    rev2 = lib.revise_template("REL_600", 10.0, settings=settings(pickup=520, tms=0.35))
    assert rev1.revision == 1 and rev2.revision == 2
    assert lib.get_template("REL_600", 1).settings[0].value == 480
    assert lib.get_template("REL_600").settings[0].value == 520
    # the original revision object is untouched
    assert rev1.settings[0].value == 480
    with pytest.raises(ValueError):
        lib.define_template("REL_600", "dup", "relay", settings(pickup=1), 0.0)
    with pytest.raises(ValueError):
        lib.get_template("REL_600", 99)


def test_chain_revisions_and_validation():
    lib = make_library()
    rev2 = lib.revise_chain("STD", 10.0, steps=("lead", "manager"))
    assert rev2.revision == 2
    assert lib.get_chain("STD", 1).steps == ("lead", "senior", "manager")
    with pytest.raises(ValueError):
        lib.define_chain("EMPTY", "empty", (), 0.0)
    with pytest.raises(ValueError):
        lib.revise_chain("STD", 11.0, steps=())


def test_duplicate_setting_key_rejected():
    lib = SettingVersionLibrary()
    with pytest.raises(ValueError):
        lib.define_template("BAD", "bad", "relay",
                            (SettingItem("pickup", 1), SettingItem("pickup", 2)), 0.0)


# -- case state machine ------------------------------------------------------

def test_draft_editable_then_locked_after_submit():
    lib = make_library()
    lib.create_case("C1", "DEV1", "REL_600", submitter="engineer", now=0.0)
    lib.revise_case("C1", settings(pickup=500, tms=0.3), now=1.0)
    assert lib.get_case("C1").settings[0].value == 500
    lib.submit_case("C1", "STD", now=2.0)
    with pytest.raises(ValueError):
        lib.revise_case("C1", settings(pickup=600), now=3.0)


def test_approval_chain_must_be_followed_in_order():
    lib = make_library()
    lib.create_case("C1", "DEV1", "REL_600", submitter="engineer", now=0.0)
    lib.submit_case("C1", "STD", now=1.0)
    # wrong actor for the first step
    with pytest.raises(ValueError):
        lib.approve("C1", "senior", 2.0)
    # duplicate approval by the same actor
    lib.approve("C1", "lead", 2.0)
    with pytest.raises(ValueError):
        lib.approve("C1", "lead", 3.0)
    # still in review until the last step approves
    assert lib.get_case("C1").state == CaseState.IN_REVIEW
    lib.approve("C1", "senior", 4.0)
    lib.approve("C1", "manager", 5.0)
    assert lib.get_case("C1").state == CaseState.APPROVED
    # approving an approved case is rejected
    with pytest.raises(ValueError):
        lib.approve("C1", "lead", 6.0)


def test_rejection_requires_current_approver_and_is_terminal():
    lib = make_library()
    lib.create_case("C1", "DEV1", "REL_600", submitter="engineer", now=0.0)
    lib.submit_case("C1", "STD", now=1.0)
    with pytest.raises(ValueError):
        lib.reject("C1", "manager", 2.0)  # not this step's approver
    lib.reject("C1", "lead", 2.0, reason="wrong study basis")
    assert lib.get_case("C1").state == CaseState.REJECTED
    with pytest.raises(ValueError):
        lib.approve("C1", "lead", 3.0)
    # continue with a new draft based on the rejected case
    lib.create_case("C2", "DEV1", "REL_600", submitter="engineer", now=4.0,
                    based_on="C1")
    assert lib.get_case("C2").based_on == "C1"
    assert lib.get_case("C2").state == CaseState.DRAFT


def test_withdrawal_only_by_submitter_and_terminal():
    lib = make_library()
    lib.create_case("C1", "DEV1", "REL_600", submitter="engineer", now=0.0)
    lib.submit_case("C1", "STD", now=1.0)
    with pytest.raises(ValueError):
        lib.withdraw("C1", "lead", 2.0)  # not the submitter
    lib.withdraw("C1", "engineer", 2.0)
    assert lib.get_case("C1").state == CaseState.WITHDRAWN
    with pytest.raises(ValueError):
        lib.release("C1", 3.0)
    # withdrawal is recorded
    actions = [r.action for r in lib.get_case("C1").approvals]
    assert actions == ["submit", "withdraw"]


def test_parallel_drafts_coexist_and_release_in_order():
    lib = make_library()
    lib.create_case("D1", "DEV1", "REL_600", submitter="engineer", now=0.0)
    lib.create_case("D2", "DEV1", "REL_600", submitter="engineer", now=1.0)
    assert {c.case_id for c in lib.list_cases(device_id="DEV1")} == {"D1", "D2"}
    v1 = approve_and_release(lib, "D1", now=10.0)
    v2 = approve_and_release(lib, "D2", now=20.0)
    # versions are numbered per device in release order
    assert v1.version_id == "DEV1@v1" and v2.version_id == "DEV1@v2"
    assert v1.sequence == 1 and v2.sequence == 2
    assert lib.current_version("DEV1").version_id == "DEV1@v2"
    # each version pins the exact template revision and chain it used
    assert v1.template_revision == 1 and v1.chain_revision == 1


def test_released_version_is_immutable():
    lib = make_library()
    version = run_to_release(lib, "C1", "DEV1")
    # frozen dataclass: attribute mutation is impossible
    with pytest.raises(AttributeError):
        version.released_at = 999.0  # type: ignore[misc]
    # the library never edits a released case
    assert lib.get_case("C1").state == CaseState.RELEASED
    with pytest.raises(ValueError):
        lib.revise_case("C1", settings(pickup=1), now=200.0)
    # double release is rejected
    with pytest.raises(ValueError):
        lib.release("C1", 200.0)
    # content hash is a stable digest of the payload
    assert len(version.content_hash) == 64
    assert version.content_hash == lib.get_version("DEV1@v1").content_hash


# -- field traceability -----------------------------------------------------

def test_field_install_traces_to_released_version_only():
    lib = make_library()
    version = run_to_release(lib, "C1", "DEV1")
    lib.install_field("DEV1", version.version_id, installed_by="crew", now=200.0,
                      note="feeder A")
    current = lib.current_field("DEV1")
    assert current is not None and current.version_id == "DEV1@v1"
    assert lib.verify_traceability("DEV1", "DEV1@v1")
    assert not lib.verify_traceability("DEV1", "DEV1@v99")
    # a version belongs to one device only
    with pytest.raises(ValueError):
        lib.install_field("DEV2", version.version_id, installed_by="crew", now=201.0)
    # unknown version cannot be installed
    with pytest.raises(ValueError):
        lib.install_field("DEV1", "DEV1@v99", installed_by="crew", now=202.0)
    # history is append-only
    lib.install_field("DEV1", version.version_id, installed_by="crew", now=203.0)
    assert len(lib.field_history("DEV1")) == 2


def test_field_cannot_reference_draft_or_approved_case():
    lib = make_library()
    lib.create_case("C1", "DEV1", "REL_600", submitter="engineer", now=0.0)
    lib.submit_case("C1", "STD", now=1.0)
    lib.approve("C1", "lead", 2.0)
    lib.approve("C1", "senior", 3.0)
    lib.approve("C1", "manager", 4.0)
    # approved but not released: no version exists yet
    with pytest.raises(ValueError):
        lib.install_field("DEV1", "DEV1@v1", installed_by="crew", now=5.0)


# -- snapshot reconstruction ------------------------------------------------

def test_snapshot_round_trip_is_verbatim():
    lib = make_library()
    run_to_release(lib, "C1", "DEV1")
    run_to_release(lib, "C2", "DEV2")
    lib.install_field("DEV1", "DEV1@v1", installed_by="crew", now=300.0)
    snapshot = lib.export_snapshot()
    assert snapshot["format"] == SNAPSHOT_FORMAT
    # JSON-safe
    json.dumps(snapshot, sort_keys=True)
    rebuilt = SettingVersionLibrary.from_snapshot(snapshot)
    assert rebuilt.export_snapshot() == snapshot
    assert rebuilt.get_version("DEV1@v1") == lib.get_version("DEV1@v1")
    assert rebuilt.current_field("DEV1") == lib.current_field("DEV1")
    assert rebuilt.get_case("C1").state == CaseState.RELEASED
    assert rebuilt.verify_traceability("DEV2", "DEV2@v1")


def test_tampered_snapshot_is_rejected():
    lib = make_library()
    run_to_release(lib, "C1", "DEV1")
    snapshot = lib.export_snapshot()
    # mutate a setting inside the export
    snapshot["versions"][0]["settings"][0]["value"] = 9999
    with pytest.raises(ValueError):
        SettingVersionLibrary.from_snapshot(snapshot)
    # digest stripped
    tampered = {k: v for k, v in snapshot.items() if k != "digest"}
    with pytest.raises(ValueError):
        SettingVersionLibrary.from_snapshot(tampered)
    # unknown format
    with pytest.raises(ValueError):
        SettingVersionLibrary.from_snapshot({"format": "other", "digest": "x"})


def test_dossier_is_self_contained_and_importable():
    lib = make_library()
    version = run_to_release(lib, "C1", "DEV1")
    dossier = lib.export_version_dossier(version.version_id)
    assert dossier["format"] == DOSSIER_FORMAT
    assert SettingVersionLibrary.verify_dossier(dossier)
    # reconstruct into an empty library from the dossier alone
    rebuilt = SettingVersionLibrary()
    rebuilt.import_version_dossier(dossier)
    assert rebuilt.get_version("DEV1@v1") == version
    assert rebuilt.get_template("REL_600", 1) == lib.get_template("REL_600", 1)
    # re-importing the same dossier conflicts
    with pytest.raises(ValueError):
        rebuilt.import_version_dossier(dossier)
    # tampered dossier fails verification and import
    dossier["version"]["settings"][0]["value"] = 1
    assert not SettingVersionLibrary.verify_dossier(dossier)
    with pytest.raises(ValueError):
        rebuilt.import_version_dossier(dossier)


def test_full_traceability_chain_from_field_to_template():
    lib = make_library()
    version = run_to_release(lib, "C1", "DEV1")
    lib.install_field("DEV1", version.version_id, installed_by="crew", now=300.0)
    # field record -> released version -> approved case -> template revision
    field = lib.current_field("DEV1")
    v = lib.get_version(field.version_id)
    case = lib.get_case(v.case_id)
    template = lib.get_template(v.template_id, v.template_revision)
    chain = lib.get_chain(v.chain_id, v.chain_revision)
    assert case.state == CaseState.RELEASED
    assert [r.action for r in v.approval_records] == [
        "submit", "approve", "approve", "approve"]
    assert template.settings[0].key == "pickup"
    assert chain.steps == ("lead", "senior", "manager")
    # every released version carries the same immutable settings snapshot
    assert v.settings == case.settings
    assert v.settings == template.settings
