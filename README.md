# RelayGrid

RelayGrid is a deterministic Python toolkit for distribution-grid operations.
It covers feeder topology, protection, voltage assessment, DER islanding,
switching safety, outage accounting, crew logistics, asset thermal limits,
telemetry quality, storage dispatch, and restoration sequencing.

The package is self-contained and uses only the Python standard library.

## Install and run

```bash
python -m pip install -e ".[test]"
relaygrid demo
python -m pytest -q
```

The demo builds a four-bus feeder with two open ties, reports its energized
state, safely closes the sectionalizing branch, and emits a JSON summary.

## Public API

The top-level package exports the feeder data model and `GridSimulator`:

```python
from relaygrid import Branch, Bus, FeederSnapshot, GridSimulator, SwitchState
```

Domain modules remain independently importable so applications can combine
topology, protection, telemetry, restoration, reliability, planning, and field
operations without depending on a web framework or database.

## Protection setting versions

The protection version repository manages immutable device templates, calculation
cases, ordered approval chains, study versions, field settings, and deterministic
snapshots:

```python
from relaygrid.protection.versioning import (
    ApprovalChain,
    CalculationCase,
    DeviceTemplate,
    ProtectionSettingRepository,
)

repository = ProtectionSettingRepository()
repository.add_approval_chain(ApprovalChain("standard", "Standard", ("engineer", "manager")))
repository.add_device_template(DeviceTemplate("recloser-a", "recloser"))
repository.add_calculation_case(CalculationCase("fault-3ph", "Fault case"))

draft = repository.create_draft(
    "feeder-12",
    "standard",
    template_ids=("recloser-a",),
    case_ids=("fault-3ph",),
    settings={"device-1": {"pickup_a": 320}},
)
repository.submit_for_approval(draft.version_id)
repository.approve(draft.version_id, "engineer")
repository.approve(draft.version_id, "manager")
published = repository.publish(draft.version_id)
repository.register_field_setting("device-1", published.version_id, {"pickup_a": 320})

# Canonical JSON can reconstruct the complete repository or a single study.
snapshot = repository.export_json()
restored = ProtectionSettingRepository.from_json(snapshot)
```

Published and approved content cannot be edited in place. Drafts may proceed in
parallel; repeated approvals, withdrawal of terminal versions, and field values
that differ from the approved study are rejected. Repository snapshots embed the
approval chain, templates, cases, hashes, field records, and event history needed
to reconstruct historical exports.

## License

RelayGrid is released under the MIT License.
