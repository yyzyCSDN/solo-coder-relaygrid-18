"""Protection setting version library.

Manages device templates, calculation (study) cases, approval chains and
exportable snapshots for protection settings.

Rules enforced by the library:

* Field settings are traceable only to *released* research versions.
* Released versions are immutable: they are content-hashed on release and
  never modified in place.
* Drafts may exist in parallel and do not block one another; releasing is
  deterministic -- versions are numbered per device in release order.
* Approval is an ordered chain: each step must be approved by the next
  expected approver; duplicate or out-of-order approvals are rejected.
* Withdrawal is only allowed by the submitter while a case is in review;
  rejected and withdrawn cases are terminal and are revised through a new
  draft case.
* Every export is content-addressed and can be reconstructed verbatim;
  tampering with a historical export is detected on import.

All timestamps are supplied by the caller so the library is fully
deterministic and has no wall-clock dependency.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Iterable

SNAPSHOT_FORMAT = "relaygrid.protection.version-library/v1"
DOSSIER_FORMAT = "relaygrid.protection.version-dossier/v1"


class CaseState(str, Enum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    RELEASED = "released"


@dataclass(frozen=True)
class SettingItem:
    """One protection setting: a key with a typed value and optional unit."""

    key: str
    value: float | str | bool
    unit: str = ""


@dataclass(frozen=True)
class DeviceTemplate:
    """Immutable revision of a device setting template."""

    template_id: str
    revision: int
    name: str
    device_type: str
    settings: tuple[SettingItem, ...]
    created_at: float


@dataclass(frozen=True)
class ApprovalChain:
    """Immutable revision of an ordered approval chain definition."""

    chain_id: str
    revision: int
    name: str
    steps: tuple[str, ...]
    created_at: float


@dataclass(frozen=True)
class ApprovalRecord:
    """One entry in a case's approval history."""

    step: int  # chain step index; -1 for submit/withdraw bookkeeping
    actor: str
    action: str  # "submit" | "approve" | "reject" | "withdraw"
    at: float
    comment: str = ""


@dataclass(frozen=True)
class StudyCase:
    """A calculation study case, moving through the approval state machine."""

    case_id: str
    device_id: str
    template_id: str
    template_revision: int
    settings: tuple[SettingItem, ...]
    state: CaseState
    submitter: str
    chain_id: str | None = None
    chain_revision: int | None = None
    based_on: str | None = None
    approvals: tuple[ApprovalRecord, ...] = ()
    created_at: float = 0.0
    updated_at: float = 0.0


@dataclass(frozen=True)
class SettingVersion:
    """A released, immutable research version of record for a device."""

    version_id: str
    device_id: str
    sequence: int
    case_id: str
    template_id: str
    template_revision: int
    chain_id: str
    chain_revision: int
    settings: tuple[SettingItem, ...]
    approval_records: tuple[ApprovalRecord, ...]
    released_at: float
    content_hash: str


@dataclass(frozen=True)
class FieldInstallation:
    """Append-only record of a released version installed on a field device."""

    device_id: str
    version_id: str
    installed_at: float
    installed_by: str
    note: str = ""


# ---------------------------------------------------------------------------
# hashing / serialization helpers
# ---------------------------------------------------------------------------

def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(obj: Any) -> str:
    return hashlib.sha256(_canonical(obj).encode("utf-8")).hexdigest()


def _validate_settings(settings: tuple[SettingItem, ...]) -> None:
    if not settings:
        raise ValueError("settings must not be empty")
    keys = [item.key for item in settings]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate setting key")


def _setting_to_dict(item: SettingItem) -> dict[str, Any]:
    return {"key": item.key, "value": item.value, "unit": item.unit}


def _setting_from_dict(data: dict[str, Any]) -> SettingItem:
    return SettingItem(data["key"], data["value"], data.get("unit", ""))


def _template_to_dict(template: DeviceTemplate) -> dict[str, Any]:
    return {
        "template_id": template.template_id,
        "revision": template.revision,
        "name": template.name,
        "device_type": template.device_type,
        "settings": [_setting_to_dict(s) for s in template.settings],
        "created_at": template.created_at,
    }


def _template_from_dict(data: dict[str, Any]) -> DeviceTemplate:
    return DeviceTemplate(
        data["template_id"], data["revision"], data["name"], data["device_type"],
        tuple(_setting_from_dict(s) for s in data["settings"]), data["created_at"],
    )


def _chain_to_dict(chain: ApprovalChain) -> dict[str, Any]:
    return {
        "chain_id": chain.chain_id,
        "revision": chain.revision,
        "name": chain.name,
        "steps": list(chain.steps),
        "created_at": chain.created_at,
    }


def _chain_from_dict(data: dict[str, Any]) -> ApprovalChain:
    return ApprovalChain(
        data["chain_id"], data["revision"], data["name"],
        tuple(data["steps"]), data["created_at"],
    )


def _record_to_dict(record: ApprovalRecord) -> dict[str, Any]:
    return {
        "step": record.step, "actor": record.actor, "action": record.action,
        "at": record.at, "comment": record.comment,
    }


def _record_from_dict(data: dict[str, Any]) -> ApprovalRecord:
    return ApprovalRecord(data["step"], data["actor"], data["action"], data["at"],
                          data.get("comment", ""))


def _case_to_dict(case: StudyCase) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "device_id": case.device_id,
        "template_id": case.template_id,
        "template_revision": case.template_revision,
        "settings": [_setting_to_dict(s) for s in case.settings],
        "state": case.state.value,
        "submitter": case.submitter,
        "chain_id": case.chain_id,
        "chain_revision": case.chain_revision,
        "based_on": case.based_on,
        "approvals": [_record_to_dict(r) for r in case.approvals],
        "created_at": case.created_at,
        "updated_at": case.updated_at,
    }


def _case_from_dict(data: dict[str, Any]) -> StudyCase:
    return StudyCase(
        data["case_id"], data["device_id"], data["template_id"],
        data["template_revision"],
        tuple(_setting_from_dict(s) for s in data["settings"]),
        CaseState(data["state"]), data["submitter"],
        data.get("chain_id"), data.get("chain_revision"), data.get("based_on"),
        tuple(_record_from_dict(r) for r in data.get("approvals", [])),
        data["created_at"], data["updated_at"],
    )


def _version_payload(version: SettingVersion) -> dict[str, Any]:
    """Canonical payload covered by the version's content hash."""
    return {
        "version_id": version.version_id,
        "device_id": version.device_id,
        "sequence": version.sequence,
        "case_id": version.case_id,
        "template_id": version.template_id,
        "template_revision": version.template_revision,
        "chain_id": version.chain_id,
        "chain_revision": version.chain_revision,
        "settings": [_setting_to_dict(s) for s in version.settings],
        "approval_records": [_record_to_dict(r) for r in version.approval_records],
        "released_at": version.released_at,
    }


def _version_to_dict(version: SettingVersion) -> dict[str, Any]:
    payload = _version_payload(version)
    payload["content_hash"] = version.content_hash
    return payload


def _version_from_dict(data: dict[str, Any]) -> SettingVersion:
    return SettingVersion(
        data["version_id"], data["device_id"], data["sequence"], data["case_id"],
        data["template_id"], data["template_revision"],
        data["chain_id"], data["chain_revision"],
        tuple(_setting_from_dict(s) for s in data["settings"]),
        tuple(_record_from_dict(r) for r in data["approval_records"]),
        data["released_at"], data["content_hash"],
    )


def _installation_to_dict(installation: FieldInstallation) -> dict[str, Any]:
    return {
        "device_id": installation.device_id,
        "version_id": installation.version_id,
        "installed_at": installation.installed_at,
        "installed_by": installation.installed_by,
        "note": installation.note,
    }


def _installation_from_dict(data: dict[str, Any]) -> FieldInstallation:
    return FieldInstallation(
        data["device_id"], data["version_id"], data["installed_at"],
        data["installed_by"], data.get("note", ""),
    )


# ---------------------------------------------------------------------------
# library
# ---------------------------------------------------------------------------

class SettingVersionLibrary:
    """In-memory library of templates, chains, cases, versions and field logs.

    The library is the single gatekeeper for the state machine: released
    versions can only be created from approved cases, field installations can
    only reference released versions, and every mutation is recorded through
    the library so that exports remain fully reconstructable.
    """

    def __init__(self) -> None:
        self._templates: dict[str, dict[int, DeviceTemplate]] = {}
        self._chains: dict[str, dict[int, ApprovalChain]] = {}
        self._cases: dict[str, StudyCase] = {}
        self._versions: dict[str, SettingVersion] = {}
        self._installations: dict[str, list[FieldInstallation]] = {}

    # -- device templates ---------------------------------------------------

    def define_template(
        self,
        template_id: str,
        name: str,
        device_type: str,
        settings: Iterable[SettingItem],
        now: float,
    ) -> DeviceTemplate:
        if not template_id:
            raise ValueError("template_id must not be empty")
        if template_id in self._templates:
            raise ValueError(
                f"template {template_id!r} already exists; use revise_template")
        settings = tuple(settings)
        _validate_settings(settings)
        template = DeviceTemplate(template_id, 1, name, device_type, settings, now)
        self._templates[template_id] = {1: template}
        return template

    def revise_template(
        self,
        template_id: str,
        now: float,
        *,
        name: str | None = None,
        device_type: str | None = None,
        settings: Iterable[SettingItem] | None = None,
    ) -> DeviceTemplate:
        """Create a new immutable revision; unspecified fields are copied."""
        current = self.get_template(template_id)
        new_settings = tuple(settings) if settings is not None else current.settings
        _validate_settings(new_settings)
        revision = DeviceTemplate(
            template_id, current.revision + 1,
            name if name is not None else current.name,
            device_type if device_type is not None else current.device_type,
            new_settings, now,
        )
        self._templates[template_id][revision.revision] = revision
        return revision

    def get_template(self, template_id: str, revision: int | None = None) -> DeviceTemplate:
        revisions = self._templates.get(template_id)
        if not revisions:
            raise ValueError(f"unknown template {template_id!r}")
        if revision is None:
            return revisions[max(revisions)]
        if revision not in revisions:
            raise ValueError(
                f"unknown template {template_id!r} revision {revision}")
        return revisions[revision]

    def list_templates(self) -> list[DeviceTemplate]:
        return [
            self._templates[tid][rev]
            for tid in sorted(self._templates)
            for rev in sorted(self._templates[tid])
        ]

    # -- approval chains ----------------------------------------------------

    def define_chain(
        self,
        chain_id: str,
        name: str,
        steps: Iterable[str],
        now: float,
    ) -> ApprovalChain:
        if not chain_id:
            raise ValueError("chain_id must not be empty")
        if chain_id in self._chains:
            raise ValueError(
                f"chain {chain_id!r} already exists; use revise_chain")
        steps = tuple(steps)
        if not steps:
            raise ValueError("approval chain must have at least one step")
        chain = ApprovalChain(chain_id, 1, name, steps, now)
        self._chains[chain_id] = {1: chain}
        return chain

    def revise_chain(
        self,
        chain_id: str,
        now: float,
        *,
        name: str | None = None,
        steps: Iterable[str] | None = None,
    ) -> ApprovalChain:
        """Create a new immutable revision; unspecified fields are copied."""
        current = self.get_chain(chain_id)
        new_steps = tuple(steps) if steps is not None else current.steps
        if not new_steps:
            raise ValueError("approval chain must have at least one step")
        revision = ApprovalChain(
            chain_id, current.revision + 1,
            name if name is not None else current.name, new_steps, now)
        self._chains[chain_id][revision.revision] = revision
        return revision

    def get_chain(self, chain_id: str, revision: int | None = None) -> ApprovalChain:
        revisions = self._chains.get(chain_id)
        if not revisions:
            raise ValueError(f"unknown approval chain {chain_id!r}")
        if revision is None:
            return revisions[max(revisions)]
        if revision not in revisions:
            raise ValueError(f"unknown approval chain {chain_id!r} revision {revision}")
        return revisions[revision]

    def list_chains(self) -> list[ApprovalChain]:
        return [
            self._chains[cid][rev]
            for cid in sorted(self._chains)
            for rev in sorted(self._chains[cid])
        ]

    # -- study cases --------------------------------------------------------

    def create_case(
        self,
        case_id: str,
        device_id: str,
        template_id: str,
        *,
        submitter: str,
        now: float,
        template_revision: int | None = None,
        settings: Iterable[SettingItem] | None = None,
        based_on: str | None = None,
    ) -> StudyCase:
        """Create a draft case.

        Settings default to the pinned template revision's settings. When
        ``based_on`` is given the new draft copies that case's settings
        (used to continue after a case was rejected or withdrawn).
        """
        if not case_id:
            raise ValueError("case_id must not be empty")
        if case_id in self._cases:
            raise ValueError(f"case {case_id!r} already exists")
        if not device_id:
            raise ValueError("device_id must not be empty")
        if not submitter:
            raise ValueError("submitter must not be empty")
        template = self.get_template(template_id, template_revision)
        if based_on is not None:
            base = self.get_case(based_on)
            base_settings = base.settings
        else:
            base_settings = None
        if settings is None:
            settings = base_settings if base_settings is not None else template.settings
        settings = tuple(settings)
        _validate_settings(settings)
        case = StudyCase(
            case_id=case_id,
            device_id=device_id,
            template_id=template.template_id,
            template_revision=template.revision,
            settings=settings,
            state=CaseState.DRAFT,
            submitter=submitter,
            based_on=based_on,
            created_at=now,
            updated_at=now,
        )
        self._cases[case_id] = case
        return case

    def revise_case(
        self,
        case_id: str,
        settings: Iterable[SettingItem],
        now: float,
    ) -> StudyCase:
        """Edit a draft case in place. Only drafts are mutable."""
        case = self.get_case(case_id)
        if case.state != CaseState.DRAFT:
            raise ValueError(
                f"case {case_id!r} is {case.state.value}; only draft cases "
                "can be edited")
        settings = tuple(settings)
        _validate_settings(settings)
        updated = replace(case, settings=settings, updated_at=now)
        self._cases[case_id] = updated
        return updated

    def get_case(self, case_id: str) -> StudyCase:
        case = self._cases.get(case_id)
        if case is None:
            raise ValueError(f"unknown case {case_id!r}")
        return case

    def list_cases(
        self,
        *,
        device_id: str | None = None,
        state: CaseState | None = None,
    ) -> list[StudyCase]:
        cases = self._cases.values()
        if device_id is not None:
            cases = (c for c in cases if c.device_id == device_id)
        if state is not None:
            cases = (c for c in cases if c.state == state)
        return sorted(cases, key=lambda c: c.case_id)

    def submit_case(
        self,
        case_id: str,
        chain_id: str,
        now: float,
        *,
        chain_revision: int | None = None,
    ) -> StudyCase:
        """Submit a draft into the approval chain (DRAFT -> IN_REVIEW)."""
        case = self.get_case(case_id)
        if case.state != CaseState.DRAFT:
            raise ValueError(
                f"case {case_id!r} is {case.state.value}; only draft cases "
                "can be submitted")
        chain = self.get_chain(chain_id, chain_revision)
        submitted = ApprovalRecord(-1, case.submitter, "submit", now)
        updated = replace(
            case,
            state=CaseState.IN_REVIEW,
            chain_id=chain.chain_id,
            chain_revision=chain.revision,
            approvals=(submitted,),
            updated_at=now,
        )
        self._cases[case_id] = updated
        return updated

    def approve(
        self,
        case_id: str,
        actor: str,
        now: float,
        *,
        comment: str = "",
    ) -> StudyCase:
        """Record one approval step.

        The actor must be the next expected approver in the chain; approving
        twice or out of order is rejected. Completing the chain moves the
        case to APPROVED.
        """
        case = self.get_case(case_id)
        if case.state != CaseState.IN_REVIEW:
            raise ValueError(
                f"case {case_id!r} is {case.state.value}; only cases in "
                "review can be approved")
        chain = self.get_chain(case.chain_id, case.chain_revision)
        approved = [r for r in case.approvals if r.action == "approve"]
        step = len(approved)
        if actor in {r.actor for r in approved}:
            raise ValueError(
                f"duplicate approval by {actor!r} on case {case_id!r}")
        expected = chain.steps[step]
        if actor != expected:
            raise ValueError(
                f"case {case_id!r} approval step {step} requires "
                f"{expected!r}, got {actor!r}")
        record = ApprovalRecord(step, actor, "approve", now, comment)
        new_state = (
            CaseState.APPROVED
            if step == len(chain.steps) - 1
            else CaseState.IN_REVIEW
        )
        updated = replace(
            case,
            state=new_state,
            approvals=case.approvals + (record,),
            updated_at=now,
        )
        self._cases[case_id] = updated
        return updated

    def reject(
        self,
        case_id: str,
        actor: str,
        now: float,
        *,
        reason: str = "",
    ) -> StudyCase:
        """Reject a case in review by the approver whose turn it is."""
        case = self.get_case(case_id)
        if case.state != CaseState.IN_REVIEW:
            raise ValueError(
                f"case {case_id!r} is {case.state.value}; only cases in "
                "review can be rejected")
        chain = self.get_chain(case.chain_id, case.chain_revision)
        step = len([r for r in case.approvals if r.action == "approve"])
        expected = chain.steps[step]
        if actor != expected:
            raise ValueError(
                f"case {case_id!r} rejection at step {step} requires "
                f"{expected!r}, got {actor!r}")
        record = ApprovalRecord(step, actor, "reject", now, reason)
        updated = replace(
            case,
            state=CaseState.REJECTED,
            approvals=case.approvals + (record,),
            updated_at=now,
        )
        self._cases[case_id] = updated
        return updated

    def withdraw(self, case_id: str, actor: str, now: float) -> StudyCase:
        """Withdraw a case from review. Only the submitter may withdraw."""
        case = self.get_case(case_id)
        if case.state != CaseState.IN_REVIEW:
            raise ValueError(
                f"case {case_id!r} is {case.state.value}; only cases in "
                "review can be withdrawn")
        if actor != case.submitter:
            raise ValueError(
                f"only the submitter {case.submitter!r} can withdraw case "
                f"{case_id!r}")
        record = ApprovalRecord(-1, actor, "withdraw", now)
        updated = replace(
            case,
            state=CaseState.WITHDRAWN,
            approvals=case.approvals + (record,),
            updated_at=now,
        )
        self._cases[case_id] = updated
        return updated

    # -- released versions --------------------------------------------------

    def release(self, case_id: str, now: float) -> SettingVersion:
        """Release an approved case as an immutable research version.

        Versions are numbered per device in release order and carry a
        content hash of their full payload. Releasing is the only way to
        create a version; released versions can never be modified.
        """
        case = self.get_case(case_id)
        if case.state != CaseState.APPROVED:
            raise ValueError(
                f"case {case_id!r} is {case.state.value}; only approved "
                "cases can be released")
        sequence = sum(
            1 for v in self._versions.values() if v.device_id == case.device_id
        ) + 1
        version_id = f"{case.device_id}@v{sequence}"
        if version_id in self._versions:  # defensive; sequence prevents this
            raise ValueError(f"version {version_id!r} already exists")
        chain = self.get_chain(case.chain_id, case.chain_revision)
        version = SettingVersion(
            version_id=version_id,
            device_id=case.device_id,
            sequence=sequence,
            case_id=case.case_id,
            template_id=case.template_id,
            template_revision=case.template_revision,
            chain_id=chain.chain_id,
            chain_revision=chain.revision,
            settings=case.settings,
            approval_records=tuple(case.approvals),
            released_at=now,
            content_hash="",
        )
        payload = _version_payload(version)
        version = replace(version, content_hash=_digest(payload))
        self._versions[version_id] = version
        self._cases[case_id] = replace(
            case, state=CaseState.RELEASED, updated_at=now)
        return version

    def get_version(self, version_id: str) -> SettingVersion:
        version = self._versions.get(version_id)
        if version is None:
            raise ValueError(f"unknown version {version_id!r}")
        return version

    def current_version(self, device_id: str) -> SettingVersion | None:
        versions = [
            v for v in self._versions.values() if v.device_id == device_id]
        if not versions:
            return None
        return max(versions, key=lambda v: v.sequence)

    def list_versions(self, device_id: str | None = None) -> list[SettingVersion]:
        versions = self._versions.values()
        if device_id is not None:
            versions = (v for v in versions if v.device_id == device_id)
        return sorted(versions, key=lambda v: (v.device_id, v.sequence))

    # -- field installations ------------------------------------------------

    def install_field(
        self,
        device_id: str,
        version_id: str,
        *,
        installed_by: str,
        now: float,
        note: str = "",
    ) -> FieldInstallation:
        """Record that a released version is installed on a field device.

        The version must exist (only released versions do) and belong to
        the given device.
        """
        version = self.get_version(version_id)
        if version.device_id != device_id:
            raise ValueError(
                f"version {version_id!r} belongs to device "
                f"{version.device_id!r}, not {device_id!r}")
        installation = FieldInstallation(
            device_id, version_id, now, installed_by, note)
        self._installations.setdefault(device_id, []).append(installation)
        return installation

    def field_history(self, device_id: str) -> list[FieldInstallation]:
        return list(self._installations.get(device_id, ()))

    def current_field(self, device_id: str) -> FieldInstallation | None:
        history = self._installations.get(device_id)
        return history[-1] if history else None

    def verify_traceability(self, device_id: str, version_id: str) -> bool:
        """Return whether ``version_id`` is a released version of the device."""
        try:
            version = self.get_version(version_id)
        except ValueError:
            return False
        return version.device_id == device_id

    # -- snapshots / reconstruction ----------------------------------------

    def export_snapshot(self) -> dict[str, Any]:
        """Export the whole library as a content-addressed snapshot.

        The returned dict is JSON-serializable and can be passed to
        :meth:`from_snapshot` to rebuild the library verbatim.
        """
        payload: dict[str, Any] = {
            "format": SNAPSHOT_FORMAT,
            "templates": [
                _template_to_dict(t)
                for t in sorted(
                    self._templates[tid][r]
                    for tid in sorted(self._templates)
                    for r in sorted(self._templates[tid]))
            ],
            "chains": [
                _chain_to_dict(c)
                for c in sorted(
                    self._chains[cid][r]
                    for cid in sorted(self._chains)
                    for r in sorted(self._chains[cid]))
            ],
            "cases": [
                _case_to_dict(c)
                for c in sorted(self._cases.values(), key=lambda c: c.case_id)
            ],
            "versions": [
                _version_to_dict(v)
                for v in sorted(
                    self._versions.values(),
                    key=lambda v: (v.device_id, v.sequence))
            ],
            "installations": [
                _installation_to_dict(i)
                for i in sorted(
                    (i for history in self._installations.values() for i in history),
                    key=lambda i: (i.device_id, i.installed_at, i.version_id))
            ],
        }
        payload["digest"] = _digest(payload)
        return payload

    @classmethod
    def from_snapshot(cls, data: dict[str, Any]) -> "SettingVersionLibrary":
        """Rebuild a library from a snapshot exported by :meth:`export_snapshot`.

        Raises ``ValueError`` if the format is unknown, the digest does not
        match (tampered or corrupt export), a version hash does not match,
        or a referenced record is missing.
        """
        if not isinstance(data, dict) or data.get("format") != SNAPSHOT_FORMAT:
            raise ValueError("not a version-library snapshot")
        expected_digest = data.get("digest")
        body = {key: value for key, value in data.items() if key != "digest"}
        if not isinstance(expected_digest, str) or _digest(body) != expected_digest:
            raise ValueError("snapshot digest mismatch; export is tampered or corrupt")

        library = cls()
        for template_data in data.get("templates", []):
            template = _template_from_dict(template_data)
            library._templates.setdefault(template.template_id, {})[
                template.revision] = template
        for chain_data in data.get("chains", []):
            chain = _chain_from_dict(chain_data)
            library._chains.setdefault(chain.chain_id, {})[chain.revision] = chain
        for case_data in data.get("cases", []):
            case = _case_from_dict(case_data)
            library._require_template(case.template_id, case.template_revision)
            if case.chain_id is not None:
                library._require_chain(case.chain_id, case.chain_revision)
            library._cases[case.case_id] = case
        for version_data in data.get("versions", []):
            version = _version_from_dict(version_data)
            if _digest(_version_payload(version)) != version.content_hash:
                raise ValueError(
                    f"content hash mismatch for version {version.version_id!r}")
            library._require_template(version.template_id, version.template_revision)
            library._require_chain(version.chain_id, version.chain_revision)
            if version.case_id not in library._cases:
                raise ValueError(
                    f"version {version.version_id!r} references missing case "
                    f"{version.case_id!r}")
            library._versions[version.version_id] = version
        for installation_data in data.get("installations", []):
            installation = _installation_from_dict(installation_data)
            if installation.version_id not in library._versions:
                raise ValueError(
                    f"installation references missing version "
                    f"{installation.version_id!r}")
            library._installations.setdefault(installation.device_id, []).append(
                installation)
        return library

    def export_version_dossier(self, version_id: str) -> dict[str, Any]:
        """Export a self-contained, verifiable dossier for one version.

        The dossier bundles the version with the exact case, template
        revision and chain revision it was built from, so a historical
        export can be verified and reconstructed independently.
        """
        version = self.get_version(version_id)
        case = self.get_case(version.case_id)
        template = self.get_template(version.template_id, version.template_revision)
        chain = self.get_chain(version.chain_id, version.chain_revision)
        payload: dict[str, Any] = {
            "format": DOSSIER_FORMAT,
            "version": _version_to_dict(version),
            "case": _case_to_dict(case),
            "template": _template_to_dict(template),
            "chain": _chain_to_dict(chain),
        }
        payload["digest"] = _digest(payload)
        return payload

    def import_version_dossier(self, data: dict[str, Any]) -> SettingVersion:
        """Verify a dossier and merge its version into this library.

        Raises ``ValueError`` on tampering or when the dossier conflicts
        with records already held by the library.
        """
        if not isinstance(data, dict) or data.get("format") != DOSSIER_FORMAT:
            raise ValueError("not a version dossier")
        expected_digest = data.get("digest")
        body = {key: value for key, value in data.items() if key != "digest"}
        if not isinstance(expected_digest, str) or _digest(body) != expected_digest:
            raise ValueError("dossier digest mismatch; export is tampered or corrupt")
        version_data = data["version"]
        version = _version_from_dict(version_data)
        if _digest(_version_payload(version)) != version.content_hash:
            raise ValueError(
                f"content hash mismatch for version {version.version_id!r}")
        if version.version_id in self._versions:
            raise ValueError(f"version {version.version_id!r} already exists")
        if version.case_id in self._cases:
            raise ValueError(f"case {version.case_id!r} already exists")
        template = _template_from_dict(data["template"])
        chain = _chain_from_dict(data["chain"])
        if (template.template_id, template.revision) in self._template_keys():
            raise ValueError(
                f"template {template.template_id!r} revision {template.revision} "
                "already exists")
        if (chain.chain_id, chain.revision) in self._chain_keys():
            raise ValueError(
                f"chain {chain.chain_id!r} revision {chain.revision} already exists")
        self._templates.setdefault(template.template_id, {})[template.revision] = template
        self._chains.setdefault(chain.chain_id, {})[chain.revision] = chain
        self._cases[version.case_id] = _case_from_dict(data["case"])
        self._versions[version.version_id] = version
        return version

    @staticmethod
    def verify_dossier(data: dict[str, Any]) -> bool:
        """Return whether a dossier is well-formed and digest-verified."""
        try:
            if not isinstance(data, dict) or data.get("format") != DOSSIER_FORMAT:
                return False
            body = {key: value for key, value in data.items() if key != "digest"}
            if not isinstance(data.get("digest"), str):
                return False
            if _digest(body) != data["digest"]:
                return False
            version = _version_from_dict(data["version"])
            return _digest(_version_payload(version)) == version.content_hash
        except (KeyError, TypeError, ValueError):
            return False

    # -- internal helpers ---------------------------------------------------

    def _require_template(self, template_id: str, revision: int) -> None:
        if template_id not in self._templates or revision not in self._templates[template_id]:
            raise ValueError(
                f"case/version references missing template {template_id!r} "
                f"revision {revision}")

    def _require_chain(self, chain_id: str, revision: int) -> None:
        if chain_id not in self._chains or revision not in self._chains[chain_id]:
            raise ValueError(
                f"case/version references missing chain {chain_id!r} "
                f"revision {revision}")

    def _template_keys(self) -> set[tuple[str, int]]:
        return {
            (tid, rev)
            for tid, revisions in self._templates.items()
            for rev in revisions
        }

    def _chain_keys(self) -> set[tuple[str, int]]:
        return {
            (cid, rev)
            for cid, revisions in self._chains.items()
            for rev in revisions
        }
