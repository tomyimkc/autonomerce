from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import manage_okf_records as okf  # noqa: E402


NOW = "2026-08-01T12:00:00Z"
PAYER = "0x1111111111111111111111111111111111111111"
PAYEE = "0x2222222222222222222222222222222222222222"


def _record(
    kind: str,
    record_id: str,
    *,
    links: list[str] | None = None,
    visibility: str = "private",
    **extra,
) -> dict:
    value = {
        "schemaVersion": okf.RECORD_SCHEMA,
        "recordId": record_id,
        "recordKind": kind,
        "status": "ready",
        "visibility": visibility,
        "createdAt": NOW,
        "updatedAt": NOW,
        "title": f"Title for {record_id}",
        "llmSummary": f"Bounded summary for {record_id}.",
        "claimBoundary": "This record is private evidence, not execution authority.",
        "sourceEvidence": ["evidence-local-001"],
        "links": links or [],
    }
    value.update(extra)
    return value


def _write_record(root: Path, value: dict, *, formatting: bool = True) -> Path:
    path = root / "records" / value["recordKind"] / f"{value['recordId']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2 if formatting else None, sort_keys=formatting)
        + "\n",
        encoding="utf-8",
    )
    return path


def _initialized(tmp_path: Path) -> Path:
    root = tmp_path / "okf"
    okf.init_workspace(root)
    return root


def test_init_is_idempotent_and_never_overwrites_user_files(
    tmp_path,
    monkeypatch,
):
    template_dir = tmp_path / "tracked-templates"
    template_dir.mkdir()
    template = template_dir / "pilot.template.json"
    template.write_text(
        json.dumps({"recordKind": "pilots", "placeholder": True}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(okf, "TEMPLATE_DIR", template_dir)

    root = tmp_path / "workspace"
    first = okf.init_workspace(root)
    manifest_before = (root / ".okf-workspace.json").read_bytes()
    copied = root / "records" / "pilots" / template.name
    copied.write_text("user-owned\n", encoding="utf-8")

    second = okf.init_workspace(root)

    assert first["manifestCreated"] is True
    assert second["manifestCreated"] is False
    assert (root / ".okf-workspace.json").read_bytes() == manifest_before
    assert copied.read_text(encoding="utf-8") == "user-owned\n"
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE((root / "records").stat().st_mode) == 0o700
    assert stat.S_IMODE((root / "wiki").stat().st_mode) == 0o700
    assert stat.S_IMODE((root / "runtime").stat().st_mode) == 0o700
    assert stat.S_IMODE((root / "runtime" / "sqlite").stat().st_mode) == 0o700
    assert (
        stat.S_IMODE((root / "runtime" / "private-evidence").stat().st_mode)
        == 0o700
    )
    assert stat.S_IMODE((root / "publication-staging").stat().st_mode) == 0o700
    assert stat.S_IMODE((root / ".okf-workspace.json").stat().st_mode) == 0o600
    assert stat.S_IMODE(copied.stat().st_mode) == 0o600
    for kind in okf.RECORD_KINDS:
        assert (root / "records" / kind).is_dir()
        assert (root / "wiki" / kind).is_dir()
        assert stat.S_IMODE((root / "records" / kind).stat().st_mode) == 0o700
        assert stat.S_IMODE((root / "wiki" / kind).stat().st_mode) == 0o700


def test_valid_build_emits_bounded_markdown_and_indexes(tmp_path):
    root = _initialized(tmp_path)
    record = _record(
        "decisions",
        "keep-dry-run",
        nextAction="Ask the owner before any testnet execution.",
        privateNotes="private material that must not enter the wiki",
    )
    _write_record(root, record)

    result = okf.build_workspace(root)

    page = root / "wiki" / "decisions" / "keep-dry-run.md"
    text = page.read_text(encoding="utf-8")
    assert result["recordCount"] == 1
    assert text.startswith("---\n")
    assert "pageType: memory" in text
    assert "recordKind: decisions" in text
    assert "## LLM summary" in text
    assert "## Claim boundary" in text
    assert "## Next action" in text
    assert "records/decisions/keep-dry-run.json" in text
    assert "private material" not in text
    assert stat.S_IMODE(page.stat().st_mode) == 0o600
    assert (root / "wiki" / "Home.md").is_file()
    assert (root / "wiki" / "decisions" / "index.md").is_file()


def test_manifest_is_fail_closed(tmp_path):
    root = _initialized(tmp_path)
    manifest_path = root / ".okf-workspace.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["movesFunds"] = True
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(okf.WorkspaceValidationError, match="movesFunds"):
        okf.validate_workspace(root)


@pytest.mark.parametrize("linked_id", ["missing-record", "pilot-one"])
def test_dangling_and_self_links_are_rejected(tmp_path, linked_id):
    root = _initialized(tmp_path)
    _write_record(
        root,
        _record("pilots", "pilot-one", links=[linked_id]),
    )

    with pytest.raises(okf.WorkspaceValidationError) as failure:
        okf.validate_workspace(root)

    expected = "link" if linked_id == "missing-record" else "itself"
    assert expected in str(failure.value)


def test_credential_bearing_keys_are_rejected_recursively(tmp_path):
    root = _initialized(tmp_path)
    _write_record(
        root,
        _record(
            "evidence",
            "bad-secret",
            nested={"deeper": {"apiKey": "not-even-needed"}},
        ),
    )

    with pytest.raises(okf.WorkspaceValidationError, match="credential-bearing"):
        okf.validate_workspace(root)


def test_private_record_rejects_bearer_token_in_notes(tmp_path):
    root = _initialized(tmp_path)
    _write_record(
        root,
        _record(
            "evidence",
            "private-bearer",
            notes=(
                "Bearer fixture-token-1234"  # secret-scan: allow-test-fixture
            ),
        ),
    )

    with pytest.raises(okf.WorkspaceValidationError, match="bearer token"):
        okf.validate_workspace(root)


@pytest.mark.parametrize(
    "extra",
    [
        {"customerEmail": "person@example.com"},
        {"redactedNotes": "Contact person@example.com for details."},
        {
            "redactedNotes": (
                "Bearer abcdefghijklmnopqrstuvwxyz"  # secret-scan: allow-test-fixture
            )
        },
        {
            "redactedNotes": (
                "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJwcml2YXRlIn0."
                "abcdefghijklmno"
            )
        },
    ],
)
def test_public_redacted_records_reject_identity_and_secret_patterns(
    tmp_path,
    extra,
):
    root = _initialized(tmp_path)
    _write_record(
        root,
        _record(
            "evidence",
            "unsafe-public-record",
            visibility="public_redacted",
            **extra,
        ),
    )

    with pytest.raises(okf.WorkspaceValidationError):
        okf.validate_workspace(root)


def test_page_is_deterministic_and_uses_canonical_json_hash(tmp_path):
    root = _initialized(tmp_path)
    value = _record("risks", "single-payment-limit")
    record_path = _write_record(root, value, formatting=True)

    okf.build_workspace(root)
    page_path = root / "wiki" / "risks" / "single-payment-limit.md"
    first_page = page_path.read_bytes()
    expected_digest = hashlib.sha256(okf._canonical_json_bytes(value)).hexdigest()
    assert expected_digest in first_page.decode("utf-8")

    record_path.write_text(
        json.dumps(dict(reversed(list(value.items()))), separators=(",", ":")),
        encoding="utf-8",
    )
    okf.build_workspace(root)

    assert page_path.read_bytes() == first_page


def test_validate_and_build_reject_symlinked_wiki_kind_without_escape(
    tmp_path,
):
    root = _initialized(tmp_path)
    _write_record(root, _record("decisions", "safe-decision"))
    outside = tmp_path / "outside-wiki"
    outside.mkdir()
    wiki_kind = root / "wiki" / "decisions"
    wiki_kind.rmdir()
    wiki_kind.symlink_to(outside, target_is_directory=True)

    with pytest.raises(okf.WorkspaceValidationError, match="symlink"):
        okf.validate_workspace(root)
    with pytest.raises(okf.WorkspaceValidationError, match="symlink"):
        okf.build_workspace(root)

    assert list(outside.iterdir()) == []


@pytest.mark.parametrize(
    "kind, extra, expected",
    [
        (
            "devpost",
            {
                "automaticSubmission": True,
                "legalAttestationsOwnerOnly": True,
                "finalSubmitted": False,
            },
            "automaticSubmission",
        ),
        (
            "devpost",
            {
                "automaticSubmission": False,
                "legalAttestationsOwnerOnly": False,
                "finalSubmitted": False,
            },
            "legalAttestationsOwnerOnly",
        ),
        (
            "payments",
            {
                "movesFunds": True,
                "network": "BASE",
                "countedAsRevenue": False,
                "payingCustomer": False,
            },
            "testnet",
        ),
        (
            "payments",
            {
                "movesFunds": True,
                "network": "ARC-TESTNET",
                "countedAsRevenue": True,
                "payingCustomer": False,
            },
            "countedAsRevenue",
        ),
        (
            "authorizations",
            {"mainnetEnabled": True, "maximumPaymentCount": 1},
            "mainnetEnabled",
        ),
        (
            "authorizations",
            {"mainnetEnabled": False, "maximumPaymentCount": 2},
            "maximumPaymentCount",
        ),
        (
            "pilots",
            {
                "network": "BASE",
                "token": "USDC",
                "amountUsdc": "0.10",
                "countedAsRevenue": False,
                "payingCustomer": False,
            },
            "pilot network",
        ),
        (
            "pilots",
            {
                "network": "ARC-TESTNET",
                "token": "USDC",
                "amountUsdc": "0.10",
                "countedAsRevenue": True,
                "payingCustomer": False,
            },
            "countedAsRevenue",
        ),
    ],
)
def test_record_specific_safety_is_fail_closed(
    tmp_path,
    kind,
    extra,
    expected,
):
    root = _initialized(tmp_path)
    _write_record(root, _record(kind, f"unsafe-{kind}", **extra))

    with pytest.raises(okf.WorkspaceValidationError, match=expected):
        okf.validate_workspace(root)


def _ready_records(root: Path, tmp_path: Path) -> None:
    circle_cli = tmp_path / "circle"
    circle_cli.write_bytes(b"pinned circle cli fixture\n")
    circle_cli.chmod(0o700)
    customer_record = tmp_path / "customer.private.json"
    customer_record.write_text(
        json.dumps(
            {
                "customerRecordId": "customer-private-001",
                "relationship": {
                    "relationshipRecordId": "relationship-private-001",
                    "classification": "external_design_partner",
                },
                "consent": {
                    "consentRecordId": "consent-private-001",
                    "status": "granted",
                    "designPartnerPilot": True,
                    "testnetMicrodeal": True,
                    "publishRedactedEvidence": True,
                },
                "buyerAgentUrl": "https://buyer.partner.example:443/a2a",
                "claims": [
                    {
                        "claim": "The partner supplied one bounded claim.",
                        "sources": [
                            {
                                "url": (
                                    "https://evidence.example/report"
                                    "?case=partner-one"
                                )
                            }
                        ],
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    partner = _record(
        "partners",
        "partner-one",
        relationshipClassification="external_design_partner",
        armsLength=True,
        recruitmentStatus="accepted",
        customerRecordId="customer-private-001",
        relationshipRecordId="relationship-private-001",
    )
    consent = _record(
        "consents",
        "consent-one",
        consentStatus="granted",
        designPartnerPilot=True,
        testnetMicrodeal=True,
        publishRedactedEvidence=True,
        customerRecordId="customer-private-001",
        consentRecordId="consent-private-001",
    )
    authorization = _record(
        "authorizations",
        "authorization-one",
        status="authorized",
        network="ARC-TESTNET",
        token="USDC",
        amountUsdc="0.10",
        maximumPaymentCount=1,
        mainnetEnabled=False,
        fundingSource="founder_sponsored_testnet",
        payerWallet=PAYER,
        payeeWallet=PAYEE,
        circleCliPath=str(circle_cli),
        circleCliSha256=hashlib.sha256(circle_cli.read_bytes()).hexdigest(),
        customerRecordPath=str(customer_record),
        sqlitePath=str(root / "runtime" / "sqlite" / "payments.sqlite3"),
        privateEvidencePath=str(
            root / "runtime" / "private-evidence" / "microdeal.private.json"
        ),
        publicEvidencePath=str(
            root / "publication-staging" / "microdeal.public.json"
        ),
        circleCliInterpreter="",
        circleCliInterpreterSha256="",
        authorizedAt="2026-08-01T00:00:00Z",
        expiresAt="2099-08-01T00:00:00Z",
        pilotRecordId="pilot-one",
        microdealId="microdeal-one",
    )
    pilot = _record(
        "pilots",
        "pilot-one",
        links=["partner-one", "consent-one", "authorization-one"],
        microdealId="microdeal-one",
        partnerRecordId="partner-one",
        consentRecordId="consent-one",
        authorizationRecordId="authorization-one",
        sellerAgentUrl="HTTPS://SELLER.EXAMPLE:443/a2a",
        network="ARC-TESTNET",
        token="USDC",
        amountUsdc="0.10",
        fundingSource="founder_sponsored_testnet",
        countedAsRevenue=False,
        payingCustomer=False,
    )
    for value in (partner, consent, authorization, pilot):
        _write_record(root, value)


def test_ready_dry_run_packet_is_argv_only_and_never_authorizes_execution(
    tmp_path,
):
    root = _initialized(tmp_path)
    _ready_records(root, tmp_path)

    packet = okf.pilot_readiness(root, "pilot-one")

    assert packet["readyForDryRun"] is True
    assert packet["readyForExecution"] is False
    assert packet["dryRunBlockers"] == []
    assert packet["dryRunCommand"][0] == sys.executable
    assert packet["dryRunCommand"][1] == str(okf.MICRODEAL_RUNNER)
    assert "--dry-run" in packet["dryRunCommand"]
    microdeal_index = packet["dryRunCommand"].index("--microdeal-id")
    assert packet["dryRunCommand"][microdeal_index + 1] == "microdeal-one"
    seller_index = packet["dryRunCommand"].index("--seller-agent-url")
    assert (
        packet["dryRunCommand"][seller_index + 1]
        == "https://seller.example/a2a"
    )
    assert "--confirm-testnet-microdeal" not in packet["dryRunCommand"]
    assert okf.EXECUTION_CONFIRMATION not in packet["dryRunCommand"]
    assert any("Fresh owner approval" in item for item in packet["executionBlockers"])
    assert any(
        okf.EXECUTION_CONFIRMATION in item
        for item in packet["executionBlockers"]
    )


@pytest.mark.parametrize(
    "kind, record_id, status, expected",
    [
        ("pilots", "pilot-one", "authorized", "pilot status must be 'ready'"),
        ("partners", "partner-one", "draft", "partner status"),
        ("consents", "consent-one", "draft", "consent record status"),
        ("authorizations", "authorization-one", "ready", "authorization status"),
    ],
)
def test_readiness_requires_safe_record_lifecycle_statuses(
    tmp_path,
    kind,
    record_id,
    status,
    expected,
):
    root = _initialized(tmp_path)
    _ready_records(root, tmp_path)
    path = root / "records" / kind / f"{record_id}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["status"] = status
    path.write_text(json.dumps(record), encoding="utf-8")

    packet = okf.pilot_readiness(root, "pilot-one")

    assert packet["readyForDryRun"] is False
    assert any(expected in item for item in packet["dryRunBlockers"])


def test_authorization_must_identify_exactly_the_selected_pilot(tmp_path):
    root = _initialized(tmp_path)
    _ready_records(root, tmp_path)
    authorization_path = (
        root / "records" / "authorizations" / "authorization-one.json"
    )
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    authorization.pop("pilotRecordId")
    authorization["authorizedPilotIds"] = ["pilot-one"]
    authorization_path.write_text(json.dumps(authorization), encoding="utf-8")

    allowed = okf.pilot_readiness(root, "pilot-one")
    authorization["authorizedPilotIds"] = ["pilot-one", "pilot-two"]
    authorization_path.write_text(json.dumps(authorization), encoding="utf-8")
    blocked = okf.pilot_readiness(root, "pilot-one")

    assert allowed["readyForDryRun"] is True
    assert blocked["readyForDryRun"] is False
    assert any(
        "authorizedPilotIds" in item for item in blocked["dryRunBlockers"]
    )


def test_changing_pilot_microdeal_id_cannot_reuse_authorization(tmp_path):
    root = _initialized(tmp_path)
    _ready_records(root, tmp_path)
    pilot_path = root / "records" / "pilots" / "pilot-one.json"
    pilot = json.loads(pilot_path.read_text(encoding="utf-8"))
    pilot["microdealId"] = "microdeal-two"
    pilot_path.write_text(json.dumps(pilot), encoding="utf-8")

    packet = okf.pilot_readiness(root, "pilot-one")

    assert packet["readyForDryRun"] is False
    assert any(
        "authorization microdealId must match pilot microdealId" in item
        for item in packet["dryRunBlockers"]
    )


def test_two_active_pilots_cannot_share_one_authorization(tmp_path):
    root = _initialized(tmp_path)
    _ready_records(root, tmp_path)
    _write_record(
        root,
        _record(
            "pilots",
            "pilot-two",
            links=["authorization-one"],
            status="ready",
        ),
    )

    packet = okf.pilot_readiness(root, "pilot-one")

    assert packet["readyForDryRun"] is False
    assert any(
        "exactly one active pilot" in item
        for item in packet["dryRunBlockers"]
    )


def test_authorized_at_cannot_be_in_the_future(tmp_path):
    root = _initialized(tmp_path)
    _ready_records(root, tmp_path)
    authorization_path = (
        root / "records" / "authorizations" / "authorization-one.json"
    )
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    authorization["authorizedAt"] = "2098-08-01T00:00:00Z"
    authorization_path.write_text(json.dumps(authorization), encoding="utf-8")

    packet = okf.pilot_readiness(root, "pilot-one")

    assert packet["readyForDryRun"] is False
    assert any(
        "authorizedAt must not be in the future" in item
        for item in packet["dryRunBlockers"]
    )


def test_authorized_record_can_never_make_execution_ready(tmp_path):
    root = _initialized(tmp_path)
    _ready_records(root, tmp_path)
    authorization_path = (
        root / "records" / "authorizations" / "authorization-one.json"
    )
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    authorization["ownerApproved"] = True
    authorization["exactExecutionConfirmation"] = okf.EXECUTION_CONFIRMATION
    authorization_path.write_text(json.dumps(authorization), encoding="utf-8")

    packet = okf.pilot_readiness(root, "pilot-one")

    assert packet["readyForDryRun"] is True
    assert packet["readyForExecution"] is False
    assert packet["executionBlockers"]


@pytest.mark.parametrize(
    "seller_url",
    [
        "https://seller.example:444/a2a",
        "https://seller.example/a2a?token=private",
        "https://user:password@seller.example/a2a",
        "https://localhost/a2a",
        "https://127.0.0.1/a2a",
    ],
)
def test_readiness_rejects_noncanonical_or_nonpublic_seller_urls(
    tmp_path,
    seller_url,
):
    root = _initialized(tmp_path)
    _ready_records(root, tmp_path)
    pilot_path = root / "records" / "pilots" / "pilot-one.json"
    pilot = json.loads(pilot_path.read_text(encoding="utf-8"))
    pilot["sellerAgentUrl"] = seller_url
    pilot_path.write_text(json.dumps(pilot), encoding="utf-8")

    packet = okf.pilot_readiness(root, "pilot-one")

    assert packet["readyForDryRun"] is False
    assert any(
        "seller URL" in blocker or "public hostname" in blocker
        for blocker in packet["dryRunBlockers"]
    )


def test_readiness_rejects_expired_authorization(tmp_path):
    root = _initialized(tmp_path)
    _ready_records(root, tmp_path)
    authorization_path = (
        root / "records" / "authorizations" / "authorization-one.json"
    )
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    authorization["expiresAt"] = "2026-08-01T00:00:00Z"
    authorization_path.write_text(json.dumps(authorization), encoding="utf-8")

    packet = okf.pilot_readiness(root, "pilot-one")

    assert packet["readyForDryRun"] is False
    assert any("expiresAt" in blocker for blocker in packet["dryRunBlockers"])


def test_readiness_rejects_invalid_customer_record(tmp_path):
    root = _initialized(tmp_path)
    _ready_records(root, tmp_path)
    customer_path = tmp_path / "customer.private.json"
    customer = json.loads(customer_path.read_text(encoding="utf-8"))
    customer["claims"] = []
    customer_path.write_text(json.dumps(customer), encoding="utf-8")

    packet = okf.pilot_readiness(root, "pilot-one")

    assert packet["readyForDryRun"] is False
    assert any(
        "claims must contain 1 to 5" in blocker
        for blocker in packet["dryRunBlockers"]
    )


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (
            lambda customer: customer["claims"][0].update(extra="unsupported"),
            "claim",
        ),
        (
            lambda customer: customer["claims"][0].update(claim="x" * 8_001),
            "size limit",
        ),
        (
            lambda customer: customer["claims"][0].update(
                sources=[
                    {"url": f"https://evidence.example/report-{index}"}
                    for index in range(26)
                ]
            ),
            "exceeds 25",
        ),
        (
            lambda customer: customer["claims"][0]["sources"][0].update(
                unexpected="field"
            ),
            "unsupported fields",
        ),
        (
            lambda customer: customer["claims"][0]["sources"][0].update(
                url="https://evidence.example/report#private"
            ),
            "HTTPS",
        ),
        (
            lambda customer: customer["claims"][0]["sources"][0].update(
                stance="invented"
            ),
            "stance",
        ),
        (
            lambda customer: customer["claims"][0]["sources"][0].update(
                sourceId="bad source id"
            ),
            "invalid characters",
        ),
        (
            lambda customer: customer["claims"][0].update(
                sources=[
                    {
                        "sourceId": "duplicate",
                        "url": "https://evidence.example/one",
                    },
                    {
                        "sourceId": "duplicate",
                        "url": "https://evidence.example/two",
                    },
                ]
            ),
            "duplicate sourceId",
        ),
        (
            lambda customer: customer["claims"][0]["sources"][0].update(
                title="x" * 501
            ),
            "size limit",
        ),
        (
            lambda customer: customer["claims"][0]["sources"][0].update(
                excerpt="x" * 8_001
            ),
            "size limit",
        ),
    ],
)
def test_customer_record_validation_reproduces_runner_constraints(
    tmp_path,
    mutate,
    expected,
):
    root = _initialized(tmp_path)
    _ready_records(root, tmp_path)
    customer_path = tmp_path / "customer.private.json"
    customer = json.loads(customer_path.read_text(encoding="utf-8"))
    mutate(customer)
    customer_path.write_text(json.dumps(customer), encoding="utf-8")

    packet = okf.pilot_readiness(root, "pilot-one")

    assert packet["readyForDryRun"] is False
    assert any(expected in item for item in packet["dryRunBlockers"])


def test_readiness_requires_all_private_paths_to_be_distinct(tmp_path):
    root = _initialized(tmp_path)
    _ready_records(root, tmp_path)
    authorization_path = (
        root / "records" / "authorizations" / "authorization-one.json"
    )
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    authorization["sqlitePath"] = authorization["customerRecordPath"]
    authorization_path.write_text(json.dumps(authorization), encoding="utf-8")

    packet = okf.pilot_readiness(root, "pilot-one")

    assert packet["readyForDryRun"] is False
    assert any("paths must be distinct" in item for item in packet["dryRunBlockers"])


@pytest.mark.parametrize(
    "field, unsafe_path, expected",
    [
        ("sqlitePath", "outside.sqlite3", "SQLite path"),
        ("privateEvidencePath", "outside.private.json", "private evidence path"),
        ("publicEvidencePath", "outside.public.json", "public evidence path"),
    ],
)
def test_output_paths_must_remain_in_workspace_owned_roots(
    tmp_path,
    field,
    unsafe_path,
    expected,
):
    root = _initialized(tmp_path)
    _ready_records(root, tmp_path)
    authorization_path = (
        root / "records" / "authorizations" / "authorization-one.json"
    )
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    authorization[field] = str(tmp_path / unsafe_path)
    authorization_path.write_text(json.dumps(authorization), encoding="utf-8")

    packet = okf.pilot_readiness(root, "pilot-one")

    assert packet["readyForDryRun"] is False
    assert any(expected in item for item in packet["dryRunBlockers"])


@pytest.mark.parametrize(
    "private_root_parts",
    [
        ("wiki", "decisions"),
        ("records", "evidence"),
        ("publication-staging",),
    ],
)
def test_configurable_roots_cannot_place_private_evidence_elsewhere(
    tmp_path,
    private_root_parts,
):
    root = _initialized(tmp_path)
    _ready_records(root, tmp_path)
    authorization_path = (
        root / "records" / "authorizations" / "authorization-one.json"
    )
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    unsafe_private_root = root.joinpath(*private_root_parts)
    authorization["privateEvidenceRoot"] = str(unsafe_private_root)
    authorization["privateEvidencePath"] = str(
        unsafe_private_root / "microdeal.private.json"
    )
    authorization["publicationStagingRoot"] = str(
        root / "records" / "evidence"
    )
    authorization["publicEvidencePath"] = str(
        root / "records" / "evidence" / "microdeal.public.json"
    )
    authorization_path.write_text(json.dumps(authorization), encoding="utf-8")

    packet = okf.pilot_readiness(root, "pilot-one")

    assert packet["readyForDryRun"] is False
    assert any(
        "must not configure private-evidence or publication roots" in item
        for item in packet["dryRunBlockers"]
    )
    assert any(
        "private evidence path must remain under" in item
        for item in packet["dryRunBlockers"]
    )


def test_output_path_rejects_original_symlink_and_directory_targets(tmp_path):
    root = _initialized(tmp_path)
    _ready_records(root, tmp_path)
    authorization_path = (
        root / "records" / "authorizations" / "authorization-one.json"
    )
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    target = root / "runtime" / "private-evidence" / "target.json"
    target.write_text("{}\n", encoding="utf-8")
    symlink = root / "runtime" / "private-evidence" / "linked.json"
    symlink.symlink_to(target)
    authorization["privateEvidencePath"] = str(symlink)
    authorization["sqlitePath"] = str(root / "runtime" / "sqlite")
    authorization_path.write_text(json.dumps(authorization), encoding="utf-8")

    packet = okf.pilot_readiness(root, "pilot-one")

    assert packet["readyForDryRun"] is False
    assert any("symlink path components" in item for item in packet["dryRunBlockers"])
    assert any(
        "directory or non-regular" in item for item in packet["dryRunBlockers"]
    )


def test_circle_cli_requires_executable_bit_without_interpreter(tmp_path):
    root = _initialized(tmp_path)
    _ready_records(root, tmp_path)
    circle_cli = tmp_path / "circle"
    circle_cli.chmod(0o600)

    packet = okf.pilot_readiness(root, "pilot-one")

    assert packet["readyForDryRun"] is False
    assert any(
        "Circle CLI must have an executable bit" in item
        for item in packet["dryRunBlockers"]
    )


def test_circle_cli_interpreter_must_be_executable(tmp_path):
    root = _initialized(tmp_path)
    _ready_records(root, tmp_path)
    circle_cli = tmp_path / "circle"
    circle_cli.chmod(0o600)
    interpreter = tmp_path / "python"
    interpreter.write_bytes(b"interpreter fixture\n")
    interpreter.chmod(0o600)
    authorization_path = (
        root / "records" / "authorizations" / "authorization-one.json"
    )
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    authorization["circleCliInterpreter"] = str(interpreter)
    authorization["circleCliInterpreterSha256"] = hashlib.sha256(
        interpreter.read_bytes()
    ).hexdigest()
    authorization_path.write_text(json.dumps(authorization), encoding="utf-8")

    blocked = okf.pilot_readiness(root, "pilot-one")
    interpreter.chmod(0o700)
    ready = okf.pilot_readiness(root, "pilot-one")

    assert blocked["readyForDryRun"] is False
    assert any(
        "interpreter must have an executable bit" in item
        for item in blocked["dryRunBlockers"]
    )
    assert ready["readyForDryRun"] is True
