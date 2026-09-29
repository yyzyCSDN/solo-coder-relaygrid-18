from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field, fields as dataclass_fields, replace
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Sequence

SNAPSHOT_SCHEMA = "relaygrid.protection-settings/1"
VERSION_EXPORT_SCHEMA = "relaygrid.study-version/1"
_UNSET = object()
_GENERATED_VERSION_ID = re.compile(r"^V\d{6}$")
_GENERATED_FIELD_ID = re.compile(r"^F\d{6}$")


class VersionStatus(str, Enum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    PUBLISHED = "published"
    WITHDRAWN = "withdrawn"


class VersionRepositoryError(Exception):
    """Base class for protection setting repository errors."""


class DuplicateVersionError(VersionRepositoryError):
    pass


class VersionNotFoundError(VersionRepositoryError):
    pass


class InvalidVersionStateError(VersionRepositoryError):
    pass


class DuplicateApprovalError(VersionRepositoryError):
    pass


class InvalidApprovalError(VersionRepositoryError):
    pass


class ArtifactNotFoundError(VersionRepositoryError):
    pass


class DuplicateArtifactError(VersionRepositoryError):
    pass


class InvalidFieldSettingError(VersionRepositoryError):
    pass


class SnapshotError(VersionRepositoryError):
    pass


def _json_safe(value: Any, path: str = "$") -> None:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must be a finite JSON number")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} contains a non-string object key")
            _json_safe(item, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _json_safe(item, f"{path}[{index}]")
        return
    raise ValueError(f"{path} is not JSON serializable")


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, _JsonRecord):
        return value.to_dict()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


@dataclass(frozen=True)
class _JsonRecord:
    def to_dict(self) -> dict[str, Any]:
        return {item.name: _plain(getattr(self, item.name)) for item in dataclass_fields(self)}


@dataclass(frozen=True)
class DeviceTemplate(_JsonRecord):
    template_id: str
    device_type: str
    manufacturer: str = ""
    model: str = ""
    parameters: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _json_safe(self.parameters, f"template {self.template_id}.parameters")
        _json_safe(self.metadata, f"template {self.template_id}.metadata")
        object.__setattr__(self, "parameters", _freeze(self.parameters))
        object.__setattr__(self, "metadata", _freeze(self.metadata))


@dataclass(frozen=True)
class CalculationCase(_JsonRecord):
    case_id: str
    title: str
    inputs: Mapping[str, Any] = field(default_factory=dict)
    results: Mapping[str, Any] = field(default_factory=dict)
    assumptions: Sequence[Any] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        prefix = f"case {self.case_id}"
        _json_safe(self.inputs, f"{prefix}.inputs")
        _json_safe(self.results, f"{prefix}.results")
        _json_safe(self.assumptions, f"{prefix}.assumptions")
        _json_safe(self.metadata, f"{prefix}.metadata")
        object.__setattr__(self, "inputs", _freeze(self.inputs))
        object.__setattr__(self, "results", _freeze(self.results))
        object.__setattr__(self, "assumptions", _freeze(self.assumptions))
        object.__setattr__(self, "metadata", _freeze(self.metadata))


@dataclass(frozen=True)
class ApprovalChain(_JsonRecord):
    chain_id: str
    name: str
    approvers: Sequence[str] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.approvers:
            raise ValueError("approval chain must contain at least one approver")
        if any(not isinstance(approver, str) or not approver for approver in self.approvers):
            raise ValueError("approval chain approvers must be non-empty strings")
        if len(set(self.approvers)) != len(self.approvers):
            raise ValueError("approval chain approvers must be unique")
        _json_safe(self.metadata, f"chain {self.chain_id}.metadata")
        object.__setattr__(self, "approvers", tuple(self.approvers))
        object.__setattr__(self, "metadata", _freeze(self.metadata))


@dataclass(frozen=True)
class ApprovalRecord(_JsonRecord):
    step: int
    approver: str
    sequence: int
    comment: str = ""


@dataclass(frozen=True)
class StudyVersion(_JsonRecord):
    version_id: str
    study_id: str
    title: str
    status: VersionStatus
    chain_id: str
    template_ids: Sequence[str] = field(default_factory=tuple)
    case_ids: Sequence[str] = field(default_factory=tuple)
    templates: Sequence[DeviceTemplate] = field(default_factory=tuple)
    cases: Sequence[CalculationCase] = field(default_factory=tuple)
    settings: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    chain: ApprovalChain | None = None
    parent_version_id: str | None = None
    revision: int | None = None
    approvals: Sequence[ApprovalRecord] = field(default_factory=tuple)
    content_hash: str | None = None
    created_seq: int = 0
    submitted_seq: int | None = None
    approved_seq: int | None = None
    published_seq: int | None = None
    withdrawn_seq: int | None = None
    created_by: str = ""

    def __post_init__(self) -> None:
        _json_safe(self.settings, f"version {self.version_id}.settings")
        object.__setattr__(self, "template_ids", tuple(self.template_ids))
        object.__setattr__(self, "case_ids", tuple(self.case_ids))
        object.__setattr__(self, "templates", tuple(self.templates))
        object.__setattr__(self, "cases", tuple(self.cases))
        object.__setattr__(self, "settings", _freeze(self.settings))
        object.__setattr__(self, "approvals", tuple(self.approvals))


@dataclass(frozen=True)
class FieldSetting(_JsonRecord):
    field_setting_id: str
    device_id: str
    version_id: str
    study_id: str
    values: Mapping[str, Any]
    content_hash: str
    sequence: int
    registered_by: str = ""

    def __post_init__(self) -> None:
        _json_safe(self.values, f"field setting {self.field_setting_id}.values")
        object.__setattr__(self, "values", _freeze(self.values))


@dataclass(frozen=True)
class RepositoryEvent(_JsonRecord):
    sequence: int
    action: str
    actor: str
    target: str
    detail: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _json_safe(self.detail, f"event {self.sequence}.detail")
        object.__setattr__(self, "detail", _freeze(self.detail))


def canonical_json(value: Any) -> str:
    """Return canonical JSON used for hashes and deterministic snapshot files."""
    return json.dumps(_plain(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def version_content_hash(version: StudyVersion) -> str:
    """Hash the protected study content, excluding lifecycle and signatures."""
    payload = {
        "study_id": version.study_id,
        "title": version.title,
        "parent_version_id": version.parent_version_id,
        "settings": version.settings,
        "device_templates": version.templates,
        "calculation_cases": version.cases,
        "approval_chain": version.chain,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


class ProtectionSettingRepository:
    """In-memory, deterministic repository for protection setting studies."""

    def __init__(self) -> None:
        self._templates: dict[str, DeviceTemplate] = {}
        self._cases: dict[str, CalculationCase] = {}
        self._chains: dict[str, ApprovalChain] = {}
        self._versions: dict[str, StudyVersion] = {}
        self._version_order: list[str] = []
        self._field_settings: dict[str, FieldSetting] = {}
        self._field_order: list[str] = []
        self._studies: dict[str, dict[str, Any]] = {}
        self._events: list[RepositoryEvent] = []
        self._version_seq = 0
        self._field_seq = 0
        self._event_seq = 0

    def add_device_template(self, template: DeviceTemplate) -> DeviceTemplate:
        self._require_identifier(template.template_id, "template id")
        if template.template_id in self._templates:
            raise DuplicateArtifactError(f"device template {template.template_id} already exists")
        self._templates[template.template_id] = template
        self._log("add_device_template", template.template_id, metadata={"device_type": template.device_type})
        return template

    def update_device_template(self, template: DeviceTemplate) -> DeviceTemplate:
        self._require_identifier(template.template_id, "template id")
        if template.template_id not in self._templates:
            raise ArtifactNotFoundError(f"device template {template.template_id} not found")
        self._templates[template.template_id] = template
        self._log("update_device_template", template.template_id, metadata={"device_type": template.device_type})
        return template

    def get_device_template(self, template_id: str) -> DeviceTemplate:
        try:
            return self._templates[template_id]
        except KeyError as exc:
            raise ArtifactNotFoundError(f"device template {template_id} not found") from exc

    def list_device_templates(self) -> tuple[DeviceTemplate, ...]:
        return tuple(self._templates[key] for key in sorted(self._templates))

    def add_calculation_case(self, case: CalculationCase) -> CalculationCase:
        self._require_identifier(case.case_id, "case id")
        if case.case_id in self._cases:
            raise DuplicateArtifactError(f"calculation case {case.case_id} already exists")
        self._cases[case.case_id] = case
        self._log("add_calculation_case", case.case_id, metadata={"title": case.title})
        return case

    def update_calculation_case(self, case: CalculationCase) -> CalculationCase:
        self._require_identifier(case.case_id, "case id")
        if case.case_id not in self._cases:
            raise ArtifactNotFoundError(f"calculation case {case.case_id} not found")
        self._cases[case.case_id] = case
        self._log("update_calculation_case", case.case_id, metadata={"title": case.title})
        return case

    def get_calculation_case(self, case_id: str) -> CalculationCase:
        try:
            return self._cases[case_id]
        except KeyError as exc:
            raise ArtifactNotFoundError(f"calculation case {case_id} not found") from exc

    def list_calculation_cases(self) -> tuple[CalculationCase, ...]:
        return tuple(self._cases[key] for key in sorted(self._cases))

    def add_approval_chain(self, chain: ApprovalChain) -> ApprovalChain:
        self._require_identifier(chain.chain_id, "chain id")
        if chain.chain_id in self._chains:
            raise DuplicateArtifactError(f"approval chain {chain.chain_id} already exists")
        self._chains[chain.chain_id] = chain
        self._log("add_approval_chain", chain.chain_id, metadata={"approvers": list(chain.approvers)})
        return chain

    def update_approval_chain(self, chain: ApprovalChain) -> ApprovalChain:
        self._require_identifier(chain.chain_id, "chain id")
        if chain.chain_id not in self._chains:
            raise ArtifactNotFoundError(f"approval chain {chain.chain_id} not found")
        self._chains[chain.chain_id] = chain
        self._log("update_approval_chain", chain.chain_id, metadata={"approvers": list(chain.approvers)})
        return chain

    def get_approval_chain(self, chain_id: str) -> ApprovalChain:
        try:
            return self._chains[chain_id]
        except KeyError as exc:
            raise ArtifactNotFoundError(f"approval chain {chain_id} not found") from exc

    def list_approval_chains(self) -> tuple[ApprovalChain, ...]:
        return tuple(self._chains[key] for key in sorted(self._chains))

    def create_draft(
        self,
        study_id: str,
        chain_id: str,
        *,
        title: str = "",
        template_ids: Sequence[str] = (),
        case_ids: Sequence[str] = (),
        settings: Mapping[str, Mapping[str, Any]] | None = None,
        version_id: str | None = None,
        parent_version_id: str | None = None,
        actor: str = "",
    ) -> StudyVersion:
        self._require_identifier(study_id, "study id")
        self._require_identifier(chain_id, "chain id")
        if version_id is not None:
            self._require_identifier(version_id, "version id")
            if version_id in self._versions:
                raise DuplicateVersionError(f"version {version_id} already exists")
            if _GENERATED_VERSION_ID.match(version_id):
                raise ValueError(f"version id {version_id} is reserved for generated ids")
        chain = self.get_approval_chain(chain_id)
        template_id_tuple = self._validate_identifier_sequence(template_ids, "template id")
        case_id_tuple = self._validate_identifier_sequence(case_ids, "case id")
        frozen_settings = self._validated_settings(settings or {})
        parent: StudyVersion | None = None
        if parent_version_id is not None:
            parent = self.get_version(parent_version_id)
            if parent.study_id != study_id:
                raise ValueError("parent version must belong to the same study")
            if parent.status not in (VersionStatus.APPROVED, VersionStatus.PUBLISHED):
                raise InvalidVersionStateError("parent version must be approved or published")

        self._version_seq += 1
        generated_id = f"V{self._version_seq:06d}"
        if version_id is None:
            version_id = generated_id

        study = self._studies.setdefault(
            study_id,
            {"next_revision": 1, "latest_published_version_id": None},
        )
        event = self._log(
            "create_draft",
            version_id,
            actor,
            {
                "study_id": study_id,
                "parent_version_id": parent_version_id,
                "parallel_drafts": True,
            },
        )
        version = StudyVersion(
            version_id=version_id,
            study_id=study_id,
            title=title,
            status=VersionStatus.DRAFT,
            chain_id=chain_id,
            template_ids=template_id_tuple,
            case_ids=case_id_tuple,
            templates=tuple(self.get_device_template(item) for item in template_id_tuple),
            cases=tuple(self.get_calculation_case(item) for item in case_id_tuple),
            settings=frozen_settings,
            chain=chain,
            parent_version_id=parent_version_id,
            created_seq=event.sequence,
            created_by=actor,
        )
        self._versions[version_id] = version
        self._version_order.append(version_id)
        return version

    def update_draft(
        self,
        version_id: str,
        *,
        title: str | object = _UNSET,
        template_ids: Sequence[str] | object = _UNSET,
        case_ids: Sequence[str] | object = _UNSET,
        settings: Mapping[str, Mapping[str, Any]] | object = _UNSET,
        actor: str = "",
    ) -> StudyVersion:
        version = self._require_version(version_id)
        self._require_state(version, VersionStatus.DRAFT)
        changes: dict[str, Any] = {}
        if title is not _UNSET:
            changes["title"] = title
        if template_ids is not _UNSET:
            identifiers = self._validate_identifier_sequence(template_ids, "template id")  # type: ignore[arg-type]
            changes["template_ids"] = identifiers
            changes["templates"] = tuple(self.get_device_template(item) for item in identifiers)
        if case_ids is not _UNSET:
            identifiers = self._validate_identifier_sequence(case_ids, "case id")  # type: ignore[arg-type]
            changes["case_ids"] = identifiers
            changes["cases"] = tuple(self.get_calculation_case(item) for item in identifiers)
        if settings is not _UNSET:
            changes["settings"] = self._validated_settings(settings)  # type: ignore[arg-type]
        if not changes:
            return version
        updated = replace(version, **changes)
        self._versions[version_id] = updated
        self._log("update_draft", version_id, actor, {"fields": sorted(changes)})
        return updated

    def submit_for_approval(self, version_id: str, actor: str = "") -> StudyVersion:
        version = self._require_version(version_id)
        self._require_state(version, VersionStatus.DRAFT)
        if version.chain is None:
            raise InvalidVersionStateError("draft is missing its approval chain")
        chain = version.chain
        event = self._log("submit_for_approval", version_id, actor, {"study_id": version.study_id})
        self._versions[version_id] = replace(
            version,
            status=VersionStatus.IN_REVIEW,
            chain=chain,
            submitted_seq=event.sequence,
        )
        return self._versions[version_id]

    def approve(self, version_id: str, approver: str, comment: str = "") -> StudyVersion:
        version = self._require_version(version_id)
        if version.status in (VersionStatus.APPROVED, VersionStatus.PUBLISHED):
            raise DuplicateApprovalError(f"version {version_id} has already completed approval")
        self._require_state(version, VersionStatus.IN_REVIEW)
        if not approver:
            raise InvalidApprovalError("approver must be a non-empty string")
        if version.chain is None:
            raise InvalidVersionStateError("submitted version is missing its approval chain")
        prior_approvers = [item.approver for item in version.approvals]
        if approver in prior_approvers:
            raise DuplicateApprovalError(f"approver {approver} has already approved version {version_id}")
        step = len(version.approvals) + 1
        try:
            expected = version.chain.approvers[step - 1]
        except IndexError as exc:
            raise InvalidApprovalError("approval chain has no remaining approver") from exc
        if approver != expected:
            raise InvalidApprovalError(f"expected approver {expected}, not {approver}")

        final = step == len(version.chain.approvers)
        event = self._log(
            "approve",
            version_id,
            approver,
            {"step": step, "final": final, "comment": comment},
        )
        record = ApprovalRecord(step=step, approver=approver, sequence=event.sequence, comment=comment)
        changes: dict[str, Any] = {"approvals": version.approvals + (record,)}
        if final:
            candidate = replace(version, **changes)
            changes["status"] = VersionStatus.APPROVED
            changes["approved_seq"] = event.sequence
            changes["content_hash"] = version_content_hash(candidate)
        self._versions[version_id] = replace(version, **changes)
        return self._versions[version_id]

    def withdraw(self, version_id: str, actor: str = "", reason: str = "") -> StudyVersion:
        version = self._require_version(version_id)
        self._require_state(version, VersionStatus.DRAFT, VersionStatus.IN_REVIEW)
        event = self._log(
            "withdraw",
            version_id,
            actor,
            {"study_id": version.study_id, "reason": reason},
        )
        self._versions[version_id] = replace(
            version,
            status=VersionStatus.WITHDRAWN,
            withdrawn_seq=event.sequence,
        )
        return self._versions[version_id]

    def publish(self, version_id: str, actor: str = "") -> StudyVersion:
        version = self._require_version(version_id)
        self._require_state(version, VersionStatus.APPROVED)
        study = self._studies[version.study_id]
        revision = int(study["next_revision"])
        event = self._log(
            "publish",
            version_id,
            actor,
            {"study_id": version.study_id, "revision": revision},
        )
        published = replace(
            version,
            status=VersionStatus.PUBLISHED,
            revision=revision,
            published_seq=event.sequence,
        )
        self._versions[version_id] = published
        study["next_revision"] = revision + 1
        study["latest_published_version_id"] = version_id
        return published

    def register_field_setting(
        self,
        device_id: str,
        version_id: str,
        values: Mapping[str, Any],
        *,
        field_setting_id: str | None = None,
        actor: str = "",
    ) -> FieldSetting:
        self._require_identifier(device_id, "device id")
        if field_setting_id is not None:
            self._require_identifier(field_setting_id, "field setting id")
            if field_setting_id in self._field_settings:
                raise DuplicateArtifactError(f"field setting {field_setting_id} already exists")
            if _GENERATED_FIELD_ID.match(field_setting_id):
                raise ValueError(f"field setting id {field_setting_id} is reserved for generated ids")
        version = self._require_version(version_id)
        if version.status not in (VersionStatus.APPROVED, VersionStatus.PUBLISHED):
            raise InvalidVersionStateError("field settings must trace to an approved study version")
        if device_id not in version.settings:
            raise InvalidFieldSettingError(f"device {device_id} is not included in version {version_id}")
        if not isinstance(values, Mapping):
            raise InvalidFieldSettingError("field values must be a mapping")
        _json_safe(values, f"field setting for {device_id}.values")
        frozen_values = _freeze(values)
        if canonical_json(frozen_values) != canonical_json(version.settings[device_id]):
            raise InvalidFieldSettingError("field values do not match the approved study values")
        if not version.content_hash:
            raise InvalidVersionStateError("approved version is missing its content hash")
        existing = next(
            (
                item
                for item in self._field_settings.values()
                if item.device_id == device_id and item.version_id == version_id
            ),
            None,
        )
        if existing is not None:
            raise DuplicateArtifactError(
                f"field setting for device {device_id} already exists for version {version_id}"
            )

        self._field_seq += 1
        generated_id = f"F{self._field_seq:06d}"
        if field_setting_id is None:
            field_setting_id = generated_id

        record = FieldSetting(
            field_setting_id=field_setting_id,
            device_id=device_id,
            version_id=version_id,
            study_id=version.study_id,
            values=frozen_values,
            content_hash=version.content_hash,
            sequence=self._field_seq,
            registered_by=actor,
        )
        self._field_settings[field_setting_id] = record
        self._field_order.append(field_setting_id)
        self._log(
            "register_field_setting",
            field_setting_id,
            actor,
            {
                "device_id": device_id,
                "version_id": version_id,
                "field_setting_sequence": record.sequence,
            },
        )
        return record

    def get_version(self, version_id: str) -> StudyVersion:
        return self._require_version(version_id)

    def list_versions(
        self,
        study_id: str | None = None,
        status: VersionStatus | str | None = None,
    ) -> tuple[StudyVersion, ...]:
        normalized_status = self._normalize_status(status)
        versions = [self._versions[key] for key in self._version_order]
        if study_id is not None:
            versions = [item for item in versions if item.study_id == study_id]
        if normalized_status is not None:
            versions = [item for item in versions if item.status == normalized_status]
        return tuple(versions)

    def latest_published_version(self, study_id: str) -> StudyVersion | None:
        study = self._studies.get(study_id)
        if not study or study["latest_published_version_id"] is None:
            return None
        return self._versions[study["latest_published_version_id"]]

    def get_field_setting(self, field_setting_id: str) -> FieldSetting:
        try:
            return self._field_settings[field_setting_id]
        except KeyError as exc:
            raise InvalidFieldSettingError(f"field setting {field_setting_id} not found") from exc

    def list_field_settings(
        self,
        *,
        device_id: str | None = None,
        version_id: str | None = None,
    ) -> tuple[FieldSetting, ...]:
        records = [self._field_settings[key] for key in self._field_order]
        if device_id is not None:
            records = [item for item in records if item.device_id == device_id]
        if version_id is not None:
            records = [item for item in records if item.version_id == version_id]
        return tuple(records)

    def trace_field_setting(self, field_setting_id: str) -> dict[str, Any]:
        record = self.get_field_setting(field_setting_id)
        version = self._require_version(record.version_id)
        version_export = self.export_version(record.version_id)
        return {
            "schema": SNAPSHOT_SCHEMA,
            "object": "field-setting-trace",
            "field_setting": record.to_dict(),
            "version": _version_data(version),
            "field_settings": version_export["field_settings"],
        }

    def events(self) -> tuple[RepositoryEvent, ...]:
        return tuple(self._events)

    def export_version(self, version_id: str) -> dict[str, Any]:
        version = self._require_version(version_id)
        return {
            "schema": VERSION_EXPORT_SCHEMA,
            "object": "study-version",
            "version": _version_data(version),
            "field_settings": [
                item.to_dict()
                for item in self.list_field_settings(version_id=version_id)
            ],
        }

    def export_snapshot(self) -> dict[str, Any]:
        return {
            "schema": SNAPSHOT_SCHEMA,
            "object": "protection-setting-repository",
            "version_seq": self._version_seq,
            "field_seq": self._field_seq,
            "event_seq": self._event_seq,
            "studies": {
                study_id: {
                    "next_revision": item["next_revision"],
                    "latest_published_version_id": item["latest_published_version_id"],
                }
                for study_id, item in sorted(self._studies.items())
            },
            "device_templates": {
                key: self._templates[key].to_dict() for key in sorted(self._templates)
            },
            "calculation_cases": {key: self._cases[key].to_dict() for key in sorted(self._cases)},
            "approval_chains": {key: self._chains[key].to_dict() for key in sorted(self._chains)},
            "versions": [_version_data(self._versions[key]) for key in self._version_order],
            "field_settings": [
                self._field_settings[key].to_dict() for key in self._field_order
            ],
            "events": [item.to_dict() for item in self._events],
        }

    def export_version_json(self, version_id: str) -> str:
        return canonical_json(self.export_version(version_id))

    @classmethod
    def from_version_json(cls, payload: str) -> "ProtectionSettingRepository":
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise SnapshotError("invalid study version export JSON") from exc
        return cls.from_version_export(data)

    def export_json(self) -> str:
        return canonical_json(self.export_snapshot())

    @classmethod
    def from_snapshot(cls, data: Mapping[str, Any]) -> "ProtectionSettingRepository":
        repo = cls()
        try:
            repo._load_snapshot(data)
        except VersionRepositoryError:
            raise
        except (TypeError, ValueError, KeyError, AttributeError) as exc:
            raise SnapshotError(f"invalid protection setting snapshot: {exc}") from exc
        return repo

    @classmethod
    def import_snapshot(cls, data: Mapping[str, Any]) -> "ProtectionSettingRepository":
        return cls.from_snapshot(data)

    @classmethod
    def from_json(cls, payload: str) -> "ProtectionSettingRepository":
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise SnapshotError("invalid protection setting snapshot JSON") from exc
        return cls.from_snapshot(data)

    @classmethod
    def from_version_export(cls, data: Mapping[str, Any]) -> "ProtectionSettingRepository":
        repo = cls()
        try:
            repo._load_version_export(data)
        except VersionRepositoryError:
            raise
        except (TypeError, ValueError, KeyError, AttributeError) as exc:
            raise SnapshotError(f"invalid study version export: {exc}") from exc
        return repo

    @classmethod
    def import_version_export(cls, data: Mapping[str, Any]) -> "ProtectionSettingRepository":
        return cls.from_version_export(data)

    def _load_version_export(self, data: Mapping[str, Any]) -> None:
        if not isinstance(data, Mapping):
            raise SnapshotError("version export must be an object")
        if data.get("schema") != VERSION_EXPORT_SCHEMA:
            raise SnapshotError("unknown study version export schema")
        if data.get("object") != "study-version":
            raise SnapshotError("export object must be study-version")
        if set(data) != {"schema", "object", "version", "field_settings"}:
            raise SnapshotError("invalid study version export fields")
        field_data = data["field_settings"]
        if not isinstance(field_data, Sequence) or isinstance(field_data, (str, bytes)):
            raise SnapshotError("exported field settings must be a list")
        version_data = data["version"]
        if not isinstance(version_data, Mapping):
            raise SnapshotError("exported version must be an object")
        chain_data = version_data.get("chain")
        if chain_data is None:
            raise SnapshotError("exported version is missing its approval chain")
        chain = _build_record(ApprovalChain, chain_data, "approval chain")
        if chain.chain_id != version_data.get("chain_id"):
            raise SnapshotError("exported version chain id does not match embedded chain")
        self._chains[chain.chain_id] = chain
        for item in version_data.get("templates", []):
            template = _build_record(DeviceTemplate, item, "device template")
            if template.template_id in self._templates:
                raise SnapshotError(f"duplicate device template {template.template_id}")
            self._templates[template.template_id] = template
        for item in version_data.get("cases", []):
            case = _build_record(CalculationCase, item, "calculation case")
            if case.case_id in self._cases:
                raise SnapshotError(f"duplicate calculation case {case.case_id}")
            self._cases[case.case_id] = case
        version = _build_version(version_data, self)
        self._versions[version.version_id] = version
        self._version_order.append(version.version_id)
        self._version_seq = 1
        self._studies[version.study_id] = {
            "next_revision": (version.revision or 0) + 1,
            "latest_published_version_id": (
                version.version_id if version.status == VersionStatus.PUBLISHED else None
            ),
        }
        for index, item in enumerate(field_data, start=1):
            setting = _build_record(FieldSetting, item, "field setting")
            if setting.version_id != version.version_id or setting.study_id != version.study_id:
                raise SnapshotError(f"field setting {setting.field_setting_id} does not belong to export")
            if setting.sequence != index:
                raise SnapshotError("exported field setting sequences must start at one and be consecutive")
            if setting.field_setting_id in self._field_settings:
                raise SnapshotError(f"duplicate field setting {setting.field_setting_id}")
            if setting.device_id not in version.settings:
                raise SnapshotError(f"field setting {setting.field_setting_id} references unknown device")
            if canonical_json(setting.values) != canonical_json(version.settings[setting.device_id]):
                raise SnapshotError(f"field setting {setting.field_setting_id} differs from approved values")
            if setting.content_hash != version.content_hash:
                raise SnapshotError(f"field setting {setting.field_setting_id} hash mismatch")
            self._field_settings[setting.field_setting_id] = setting
            self._field_order.append(setting.field_setting_id)
        self._field_seq = len(self._field_settings)
        self._validate_versions()
        self._validate_field_settings()

    def _load_snapshot(self, data: Mapping[str, Any]) -> None:
        if not isinstance(data, Mapping):
            raise SnapshotError("snapshot must be an object")
        if data.get("schema") != SNAPSHOT_SCHEMA:
            raise SnapshotError("unknown protection setting snapshot schema")
        if data.get("object") != "protection-setting-repository":
            raise SnapshotError("snapshot object must be protection-setting-repository")
        allowed = {
            "schema",
            "object",
            "version_seq",
            "field_seq",
            "event_seq",
            "studies",
            "device_templates",
            "calculation_cases",
            "approval_chains",
            "versions",
            "field_settings",
            "events",
        }
        unknown = set(data) - allowed
        if unknown:
            raise SnapshotError(f"unknown snapshot fields: {sorted(unknown)}")

        version_seq = _required_int(data, "version_seq")
        field_seq = _required_int(data, "field_seq")
        event_seq = _required_int(data, "event_seq")
        studies_data = _required_mapping(data, "studies")
        templates_data = _required_mapping(data, "device_templates")
        cases_data = _required_mapping(data, "calculation_cases")
        chains_data = _required_mapping(data, "approval_chains")
        versions_data = _required_sequence(data, "versions")
        fields_data = _required_sequence(data, "field_settings")
        events_data = _required_sequence(data, "events")

        for template_id, item in templates_data.items():
            template = _build_record(DeviceTemplate, item, "device template")
            if template.template_id != template_id:
                raise SnapshotError("device template key does not match its id")
            if template_id in self._templates:
                raise SnapshotError(f"duplicate device template {template_id}")
            self._templates[template_id] = template

        for case_id, item in cases_data.items():
            case = _build_record(CalculationCase, item, "calculation case")
            if case.case_id != case_id:
                raise SnapshotError("calculation case key does not match its id")
            if case_id in self._cases:
                raise SnapshotError(f"duplicate calculation case {case_id}")
            self._cases[case_id] = case

        for chain_id, item in chains_data.items():
            chain = _build_record(ApprovalChain, item, "approval chain")
            if chain.chain_id != chain_id:
                raise SnapshotError("approval chain key does not match its id")
            if chain_id in self._chains:
                raise SnapshotError(f"duplicate approval chain {chain_id}")
            self._chains[chain_id] = chain

        for study_id, item in studies_data.items():
            if not isinstance(study_id, str) or not study_id:
                raise SnapshotError("study ids must be non-empty strings")
            if not isinstance(item, Mapping):
                raise SnapshotError(f"study {study_id} must be an object")
            next_revision = item.get("next_revision")
            latest_id = item.get("latest_published_version_id")
            if not isinstance(next_revision, int) or next_revision < 1:
                raise SnapshotError(f"study {study_id} has an invalid next revision")
            if latest_id is not None and not isinstance(latest_id, str):
                raise SnapshotError(f"study {study_id} has an invalid latest version")
            self._studies[study_id] = {
                "next_revision": next_revision,
                "latest_published_version_id": latest_id,
            }

        for item in versions_data:
            version = _build_version(item, self)
            if version.version_id in self._versions:
                raise SnapshotError(f"duplicate version {version.version_id}")
            self._versions[version.version_id] = version
            self._version_order.append(version.version_id)
            self._studies.setdefault(
                version.study_id,
                {"next_revision": 1, "latest_published_version_id": None},
            )

        for item in fields_data:
            setting = _build_record(FieldSetting, item, "field setting")
            if setting.field_setting_id in self._field_settings:
                raise SnapshotError(f"duplicate field setting {setting.field_setting_id}")
            if setting.version_id not in self._versions:
                raise SnapshotError(f"field setting {setting.field_setting_id} references unknown version")
            version = self._versions[setting.version_id]
            if setting.study_id != version.study_id:
                raise SnapshotError(f"field setting {setting.field_setting_id} has wrong study id")
            if setting.device_id not in version.settings:
                raise SnapshotError(f"field setting {setting.field_setting_id} references unknown device")
            if _plain(setting.values) != _plain(version.settings[setting.device_id]):
                raise SnapshotError(f"field setting {setting.field_setting_id} differs from approved values")
            if setting.content_hash != version.content_hash:
                raise SnapshotError(f"field setting {setting.field_setting_id} hash mismatch")
            self._field_settings[setting.field_setting_id] = setting
            self._field_order.append(setting.field_setting_id)

        for sequence, item in enumerate(events_data, start=1):
            event = _build_record(RepositoryEvent, item, "event")
            if event.sequence != sequence:
                raise SnapshotError("event sequences must be consecutive")
            self._validate_event_payload(event)
            self._events.append(event)

        self._version_order.sort(key=lambda identifier: self._versions[identifier].created_seq)
        self._field_order.sort(key=lambda identifier: self._field_settings[identifier].sequence)

        if version_seq < len(self._versions):
            raise SnapshotError("version_seq does not cover all versions")
        if field_seq < len(self._field_settings):
            raise SnapshotError("field_seq does not cover all field settings")
        if event_seq != len(self._events):
            raise SnapshotError("event_seq must equal the number of events")
        if self._event_seq != 0:
            raise SnapshotError("internal event counter was initialized incorrectly")
        self._version_seq = version_seq
        self._field_seq = field_seq
        self._event_seq = event_seq
        self._validate_versions(self._events)
        self._validate_field_settings()
        self._validate_studies()

    def _validate_versions(self, events: Sequence[RepositoryEvent] | None = None) -> None:
        event_map = {event.sequence: event for event in events or []}
        for version in self._versions.values():
            self._validate_version_lifecycle(version, event_map)

    def _validate_version_lifecycle(
        self,
        version: StudyVersion,
        event_map: Mapping[int, RepositoryEvent],
    ) -> None:
        if version.chain is None:
            raise SnapshotError(f"version {version.version_id} is missing its approval chain")
        self._require_lifecycle_event(
            version,
            event_map,
            version.created_seq,
            "create_draft",
            version.version_id,
        )
        if version.parent_version_id is not None and event_map:
            parent = self._versions.get(version.parent_version_id)
            if parent is None or parent.study_id != version.study_id:
                raise SnapshotError(f"version {version.version_id} has an invalid parent")
            if parent.status not in (VersionStatus.APPROVED, VersionStatus.PUBLISHED):
                raise SnapshotError(f"version {version.version_id} parent is not approved")

        approval_count = len(version.chain.approvers)
        for index, record in enumerate(version.approvals, start=1):
            if record.step != index:
                raise SnapshotError(f"version {version.version_id} approval steps are not consecutive")
            if record.approver != version.chain.approvers[index - 1]:
                raise SnapshotError(f"version {version.version_id} approver chain is inconsistent")
            if index > 1 and record.sequence <= version.approvals[index - 2].sequence:
                raise SnapshotError(f"version {version.version_id} approval sequences are not ordered")
            event = self._require_lifecycle_event(
                version,
                event_map,
                record.sequence,
                "approve",
                version.version_id,
                record.approver,
            )
            if event is not None and (
                event.detail.get("step") != index
                or event.detail.get("final") != (index == approval_count)
            ):
                raise SnapshotError(f"version {version.version_id} approval event detail is inconsistent")

        status = version.status
        if status == VersionStatus.DRAFT:
            self._require_null_terminal(
                version,
                ("submitted_seq", "approved_seq", "published_seq", "withdrawn_seq"),
            )
            if version.approvals or version.revision is not None or version.content_hash is not None:
                raise SnapshotError(f"draft version {version.version_id} contains terminal approval data")
        elif status == VersionStatus.IN_REVIEW:
            self._require_sequence(version, version.submitted_seq, version.created_seq, "submitted")
            self._require_null_terminal(version, ("approved_seq", "published_seq", "withdrawn_seq"))
            if len(version.approvals) >= approval_count:
                raise SnapshotError(f"version {version.version_id} has all approvals but is in review")
            if version.approvals and version.approvals[0].sequence <= version.submitted_seq:
                raise SnapshotError(f"version {version.version_id} approval precedes submission")
            self._require_lifecycle_event(
                version,
                event_map,
                version.submitted_seq or 0,
                "submit_for_approval",
                version.version_id,
            )
            if version.revision is not None or version.content_hash is not None:
                raise SnapshotError(f"in-review version {version.version_id} contains final approval data")
        elif status == VersionStatus.APPROVED:
            self._validate_complete_approvals(version, event_map)
            self._require_null_terminal(version, ("published_seq", "withdrawn_seq"))
            if version.revision is not None:
                raise SnapshotError(f"approved version {version.version_id} already has a revision")
        elif status == VersionStatus.PUBLISHED:
            self._validate_complete_approvals(version, event_map)
            self._require_sequence(version, version.published_seq, version.approved_seq or 0, "published")
            self._require_null_terminal(version, ("withdrawn_seq",))
            if not isinstance(version.revision, int) or version.revision < 1:
                raise SnapshotError(f"published version {version.version_id} has no revision")
            self._require_lifecycle_event(
                version,
                event_map,
                version.published_seq or 0,
                "publish",
                version.version_id,
            )
        elif status == VersionStatus.WITHDRAWN:
            if version.withdrawn_seq is None or version.withdrawn_seq <= version.created_seq:
                raise SnapshotError(f"withdrawn version {version.version_id} has no withdrawal sequence")
            if version.submitted_seq is not None:
                self._require_sequence(version, version.submitted_seq, version.created_seq, "submitted")
                if version.approvals and version.approvals[0].sequence <= version.submitted_seq:
                    raise SnapshotError(f"version {version.version_id} approval precedes submission")
            if version.approved_seq is not None or version.published_seq is not None:
                raise SnapshotError(f"withdrawn version {version.version_id} has terminal approval data")
            if len(version.approvals) >= approval_count:
                raise SnapshotError(f"withdrawn version {version.version_id} completed approval")
            self._require_lifecycle_event(
                version,
                event_map,
                version.withdrawn_seq or 0,
                "withdraw",
                version.version_id,
            )
        else:  # Defensive; enum construction already validates serialized values.
            raise SnapshotError(f"unknown lifecycle status {status}")

    def _validate_complete_approvals(
        self,
        version: StudyVersion,
        event_map: Mapping[int, RepositoryEvent],
    ) -> None:
        if version.chain is None:
            raise SnapshotError(f"version {version.version_id} is missing its approval chain")
        if len(version.approvals) != len(version.chain.approvers):
            raise SnapshotError(f"version {version.version_id} approvals are incomplete")
        self._require_sequence(version, version.submitted_seq, version.created_seq, "submitted", True)
        if version.approvals[0].sequence <= version.submitted_seq:
            raise SnapshotError(f"version {version.version_id} first approval precedes submission")
        self._require_sequence(version, version.approved_seq, version.approvals[-1].sequence, "approved", False)
        if version.content_hash != version_content_hash(version):
            raise SnapshotError(f"version {version.version_id} content hash mismatch")
        self._require_lifecycle_event(
            version,
            event_map,
            version.submitted_seq or 0,
            "submit_for_approval",
            version.version_id,
        )

    def _validate_field_settings(self) -> None:
        seen_pairs: set[tuple[str, str]] = set()
        sequences: list[int] = []
        for setting in self._field_settings.values():
            version = self._versions.get(setting.version_id)
            if version is None:
                raise SnapshotError(f"field setting {setting.field_setting_id} references unknown version")
            if version.status not in (VersionStatus.APPROVED, VersionStatus.PUBLISHED):
                raise SnapshotError(f"field setting {setting.field_setting_id} is not tied to an approval")
            pair = (setting.device_id, setting.version_id)
            if pair in seen_pairs:
                raise SnapshotError(f"duplicate field setting for {setting.device_id}/{setting.version_id}")
            seen_pairs.add(pair)
            sequences.append(setting.sequence)
            register_event = next(
                (
                    event
                    for event in self._events
                    if event.action == "register_field_setting"
                    and event.target == setting.field_setting_id
                ),
                None,
            )
            if self._events and register_event is None:
                raise SnapshotError(f"field setting {setting.field_setting_id} is missing its event")
            if register_event is not None and (
                register_event.detail.get("device_id") != setting.device_id
                or register_event.detail.get("version_id") != setting.version_id
                or register_event.detail.get("field_setting_sequence") != setting.sequence
            ):
                raise SnapshotError(f"field setting {setting.field_setting_id} event detail is inconsistent")
        register_events = [
            event for event in self._events if event.action == "register_field_setting"
        ]
        if self._events and len(register_events) != len(self._field_settings):
            raise SnapshotError("field setting events do not match field settings")
        for index, event in enumerate(sorted(register_events, key=lambda item: item.sequence), start=1):
            if event.detail.get("field_setting_sequence") != index:
                raise SnapshotError("field setting events are not ordered by setting sequence")
        if sequences and (min(sequences) < 1 or sorted(sequences) != list(range(min(sequences), max(sequences) + 1))):
            raise SnapshotError("field setting sequences must be consecutive positive integers")
        if sequences and max(sequences) > self._field_seq:
            raise SnapshotError("field_seq does not cover field setting sequences")

    @staticmethod
    def _validate_event_payload(event: RepositoryEvent) -> None:
        if not event.action or not event.target:
            raise SnapshotError("events must include an action and target")
        if not isinstance(event.actor, str):
            raise SnapshotError("event actors must be strings")
        if event.action == "approve" and (
            "step" not in event.detail or "final" not in event.detail
        ):
            raise SnapshotError("approval event is missing required detail")
        if event.action == "register_field_setting" and (
            "device_id" not in event.detail
            or "version_id" not in event.detail
            or "field_setting_sequence" not in event.detail
        ):
            raise SnapshotError("field setting event is missing required detail")

    @staticmethod
    def _require_null_terminal(version: StudyVersion, names: Sequence[str]) -> None:
        for name in names:
            if getattr(version, name) is not None:
                raise SnapshotError(f"version {version.version_id} has unexpected {name}")

    @staticmethod
    def _require_sequence(
        version: StudyVersion,
        value: int | None,
        previous: int,
        label: str,
        strict: bool = True,
    ) -> None:
        if value is None or (value < previous if not strict else value <= previous):
            raise SnapshotError(f"version {version.version_id} has invalid {label} sequence")

    @staticmethod
    def _require_lifecycle_event(
        version: StudyVersion,
        event_map: Mapping[int, RepositoryEvent],
        sequence: int,
        action: str,
        target: str,
        expected_actor: str | None = None,
    ) -> RepositoryEvent | None:
        if not event_map:
            return None
        if sequence < 1 or sequence not in event_map:
            raise SnapshotError(f"version {version.version_id} is missing event {sequence}")
        event = event_map[sequence]
        if event.action != action or event.target != target:
            raise SnapshotError(f"version {version.version_id} event {sequence} does not match lifecycle")
        if expected_actor is not None and event.actor != expected_actor:
            raise SnapshotError(f"version {version.version_id} event {sequence} actor is inconsistent")
        if event.detail.get("study_id") not in (None, version.study_id):
            raise SnapshotError(f"version {version.version_id} event study id is inconsistent")
        return event

    def _validate_studies(self) -> None:
        published = {
            study_id: [
                version
                for version in self._versions.values()
                if version.study_id == study_id and version.status == VersionStatus.PUBLISHED
            ]
            for study_id in self._studies
        }
        for study_id, versions in published.items():
            revisions = sorted(version.revision for version in versions)
            if revisions != list(range(1, len(versions) + 1)):
                raise SnapshotError(f"study {study_id} has non-contiguous published revisions")
            study = self._studies[study_id]
            if versions:
                latest = max(versions, key=lambda item: item.revision or 0)
                if study["latest_published_version_id"] != latest.version_id:
                    raise SnapshotError(f"study {study_id} latest published pointer is invalid")
                if study["next_revision"] != len(versions) + 1:
                    raise SnapshotError(f"study {study_id} next revision is invalid")
            elif study["latest_published_version_id"] is not None:
                raise SnapshotError(f"study {study_id} has a latest pointer without published versions")

    def _log(
        self,
        action: str,
        target: str = "",
        actor: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> RepositoryEvent:
        _json_safe(metadata or {}, "event detail")
        self._event_seq += 1
        event = RepositoryEvent(
            sequence=self._event_seq,
            action=action,
            actor=actor,
            target=target,
            detail=metadata or {},
        )
        self._events.append(event)
        return event

    def _require_version(self, version_id: str) -> StudyVersion:
        try:
            return self._versions[version_id]
        except KeyError as exc:
            raise VersionNotFoundError(f"version {version_id} not found") from exc

    @staticmethod
    def _require_state(version: StudyVersion, *states: VersionStatus) -> None:
        if version.status not in states:
            allowed = ", ".join(sorted(item.value for item in states))
            raise InvalidVersionStateError(
                f"version {version.version_id} is {version.status.value}; expected {allowed}"
            )

    @staticmethod
    def _require_identifier(value: str, label: str) -> None:
        if not isinstance(value, str) or not value:
            raise ValueError(f"{label} must be a non-empty string")

    @staticmethod
    def _validate_identifier_sequence(values: Sequence[str], label: str) -> tuple[str, ...]:
        if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
            raise ValueError(f"{label} sequence must be a sequence of strings")
        result = tuple(values)
        for item in result:
            ProtectionSettingRepository._require_identifier(item, label)
        return result

    @staticmethod
    def _validated_settings(settings: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(settings, Mapping):
            raise ValueError("settings must be a mapping")
        for device_id, values in settings.items():
            if not isinstance(device_id, str) or not device_id:
                raise ValueError("setting device ids must be non-empty strings")
            if not isinstance(values, Mapping):
                raise ValueError(f"settings for device {device_id} must be a mapping")
            _json_safe(values, f"settings.{device_id}")
        return _freeze(settings)

    @staticmethod
    def _normalize_status(status: VersionStatus | str | None) -> VersionStatus | None:
        if status is None:
            return None
        if isinstance(status, VersionStatus):
            return status
        try:
            return VersionStatus(status)
        except ValueError as exc:
            raise ValueError(f"unknown version status {status}") from exc


def _required_mapping(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data.get(key)
    if not isinstance(value, Mapping):
        raise SnapshotError(f"snapshot field {key} must be an object")
    return value


def _required_sequence(data: Mapping[str, Any], key: str) -> Sequence[Any]:
    value = data.get(key)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise SnapshotError(f"snapshot field {key} must be a list")
    return value


def _required_int(data: Mapping[str, Any], key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SnapshotError(f"snapshot field {key} must be a non-negative integer")
    return value


def _record_field_names(record_class: type[_JsonRecord]) -> set[str]:
    return {item.name for item in dataclass_fields(record_class)}


def _build_record(record_class: type[_JsonRecord], data: Any, label: str) -> Any:
    if not isinstance(data, Mapping):
        raise SnapshotError(f"{label} must be an object")
    field_names = _record_field_names(record_class)
    unknown = set(data) - field_names
    if unknown:
        raise SnapshotError(f"unknown {label} fields: {sorted(unknown)}")
    missing = field_names - set(data)
    if missing:
        raise SnapshotError(f"missing {label} fields: {sorted(missing)}")
    return record_class(**{key: data[key] for key in field_names})


def _build_version(data: Any, repo: ProtectionSettingRepository) -> StudyVersion:
    if not isinstance(data, Mapping):
        raise SnapshotError("version must be an object")
    field_names = _record_field_names(StudyVersion)
    unknown = set(data) - field_names
    if unknown:
        raise SnapshotError(f"unknown version fields: {sorted(unknown)}")
    missing = field_names - set(data)
    if missing:
        raise SnapshotError(f"missing version fields: {sorted(missing)}")

    status_value = data["status"]
    try:
        status = VersionStatus(status_value)
    except ValueError as exc:
        raise SnapshotError(f"unknown version status {status_value}") from exc
    chain_data = data["chain"]
    chain = None if chain_data is None else _build_record(ApprovalChain, chain_data, "approval chain")
    if chain is not None and chain.chain_id != data["chain_id"]:
        raise SnapshotError("version chain id does not match embedded chain")
    if data["chain_id"] not in repo._chains:
        raise SnapshotError(f"version {data['version_id']} references unknown chain")
    catalog_chain = repo._chains[data["chain_id"]]
    if chain is not None and chain.to_dict() != catalog_chain.to_dict():
        raise SnapshotError(f"version {data['version_id']} embedded chain differs from catalog")
    if chain is None:
        raise SnapshotError(f"version {data['version_id']} is missing its approval chain")

    templates = tuple(_build_record(DeviceTemplate, item, "device template") for item in data["templates"])
    cases = tuple(_build_record(CalculationCase, item, "calculation case") for item in data["cases"])
    approvals = tuple(_build_record(ApprovalRecord, item, "approval record") for item in data["approvals"])
    template_ids = tuple(data["template_ids"])
    case_ids = tuple(data["case_ids"])
    if tuple(item.template_id for item in templates) != template_ids:
        raise SnapshotError(f"version {data['version_id']} template ids do not match templates")
    if tuple(item.case_id for item in cases) != case_ids:
        raise SnapshotError(f"version {data['version_id']} case ids do not match cases")
    for template in templates:
        catalog = repo._templates.get(template.template_id)
        if catalog is None or catalog.to_dict() != template.to_dict():
            raise SnapshotError(f"version {data['version_id']} template {template.template_id} is not in catalog")
    for case in cases:
        catalog = repo._cases.get(case.case_id)
        if catalog is None or catalog.to_dict() != case.to_dict():
            raise SnapshotError(f"version {data['version_id']} case {case.case_id} is not in catalog")

    settings = data["settings"]
    if not isinstance(settings, Mapping):
        raise SnapshotError("version settings must be an object")
    version = StudyVersion(
        version_id=data["version_id"],
        study_id=data["study_id"],
        title=data["title"],
        status=status,
        chain_id=data["chain_id"],
        template_ids=template_ids,
        case_ids=case_ids,
        templates=templates,
        cases=cases,
        settings=settings,
        chain=chain,
        parent_version_id=data["parent_version_id"],
        revision=data["revision"],
        approvals=approvals,
        content_hash=data["content_hash"],
        created_seq=data["created_seq"],
        submitted_seq=data["submitted_seq"],
        approved_seq=data["approved_seq"],
        published_seq=data["published_seq"],
        withdrawn_seq=data["withdrawn_seq"],
        created_by=data["created_by"],
    )
    if status in (VersionStatus.APPROVED, VersionStatus.PUBLISHED):
        if version.content_hash != version_content_hash(version):
            raise SnapshotError(f"version {version.version_id} content hash mismatch")
    else:
        if version.content_hash is not None:
            raise SnapshotError(f"version {version.version_id} contains an untimely content hash")
    if version.revision is not None and (isinstance(version.revision, bool) or not isinstance(version.revision, int)):
        raise SnapshotError(f"version {version.version_id} revision must be an integer or null")
    for name in ("created_seq", "submitted_seq", "approved_seq", "published_seq", "withdrawn_seq"):
        value = getattr(version, name)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
            raise SnapshotError(f"version {version.version_id} has an invalid {name}")
    return version


def _version_data(version: StudyVersion) -> dict[str, Any]:
    return version.to_dict()


VersionRepository = ProtectionSettingRepository
SettingVersionRepository = ProtectionSettingRepository
ProtectionSettingVersionRepository = ProtectionSettingRepository
ProtectionSettingVersionStore = ProtectionSettingRepository
ProtectionSettingVersionLibrary = ProtectionSettingRepository

__all__ = [
    "SNAPSHOT_SCHEMA",
    "ApprovalChain",
    "ApprovalRecord",
    "CalculationCase",
    "DeviceTemplate",
    "DuplicateApprovalError",
    "DuplicateArtifactError",
    "DuplicateVersionError",
    "FieldSetting",
    "InvalidApprovalError",
    "InvalidFieldSettingError",
    "InvalidVersionStateError",
    "ProtectionSettingRepository",
    "ProtectionSettingVersionLibrary",
    "ProtectionSettingVersionRepository",
    "ProtectionSettingVersionStore",
    "RepositoryEvent",
    "SettingVersionRepository",
    "SnapshotError",
    "StudyVersion",
    "VERSION_EXPORT_SCHEMA",
    "VersionNotFoundError",
    "VersionRepository",
    "VersionStatus",
    "canonical_json",
    "version_content_hash",
]
