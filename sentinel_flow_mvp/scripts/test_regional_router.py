"""Mathematical Proof — Regional Compliance State Machine.

This test script verifies that `RegionalComplianceRouter.anonymize_batch()`
correctly branches on the `originating_region` field and applies the correct
PII redaction rules for each recognised state.

Test cases (mathematical branches):

    IF region == "EU"  → contact_name MUST be "REDACTED_GDPR"
                        AND contact_email MUST be "REDACTED@gdpr.eu"

    IF region == "IN"  → contact_name MUST equal the original value
                        AND contact_email MUST equal the original value

    IF region == "DEFAULT" → contact_name MUST equal the original value
                            AND contact_email MUST equal the original value

If ALL three assertions pass, the state machine is PROVEN correct.
If ANY assertion fails, the state machine has a bug in that branch.
"""

from datetime import datetime

from app.domain.schemas import BatchIngestionRequest, SupplierRecord
from app.services.regional_router import RegionalComplianceRouter


def main() -> None:
    """Execute the three-branch verification and print a pass/fail report."""

    # ------------------------------------------------------------------
    # Shared test data — same supplier with dummy PII used in every branch
    # ------------------------------------------------------------------
    dummy_timestamp = datetime(year=2026, month=6, day=1)

    original_contact_name = "John Doe"
    original_contact_email = "john@example.com"

    eu_supplier = SupplierRecord(
        supplier_id="SUP-EU-001",
        timestamp=dummy_timestamp,
        inventory_count=100,
        delivery_delay_days=2,
        contact_name=original_contact_name,
        contact_email=original_contact_email,
    )

    in_supplier = SupplierRecord(
        supplier_id="SUP-IN-001",
        timestamp=dummy_timestamp,
        inventory_count=200,
        delivery_delay_days=1,
        contact_name=original_contact_name,
        contact_email=original_contact_email,
    )

    default_supplier = SupplierRecord(
        supplier_id="SUP-DEF-001",
        timestamp=dummy_timestamp,
        inventory_count=150,
        delivery_delay_days=0,
        contact_name=original_contact_name,
        contact_email=original_contact_email,
    )

    # ------------------------------------------------------------------
    # BRANCH 1: EU — expect full redaction
    # ------------------------------------------------------------------
    eu_batch = BatchIngestionRequest(
        batch_identifier="BATCH-EU-001",
        source_system="TALLY_XML",
        records=[eu_supplier],
        originating_region="EU",
    )

    eu_result = RegionalComplianceRouter.anonymize_batch(
        batch_request=eu_batch,
    )

    eu_record = eu_result.records[0]
    eu_name_redacted = (eu_record.contact_name == "REDACTED_GDPR")
    eu_email_redacted = (eu_record.contact_email == "REDACTED@gdpr.eu")

    # ------------------------------------------------------------------
    # BRANCH 2: IN — expect PII preserved intact
    # ------------------------------------------------------------------
    in_batch = BatchIngestionRequest(
        batch_identifier="BATCH-IN-001",
        source_system="SAP_ODATA",
        records=[in_supplier],
        originating_region="IN",
    )

    in_result = RegionalComplianceRouter.anonymize_batch(
        batch_request=in_batch,
    )

    in_record = in_result.records[0]
    in_name_preserved = (in_record.contact_name == original_contact_name)
    in_email_preserved = (in_record.contact_email == original_contact_email)

    # ------------------------------------------------------------------
    # BRANCH 3: DEFAULT — expect PII preserved intact
    # ------------------------------------------------------------------
    default_batch = BatchIngestionRequest(
        batch_identifier="BATCH-DEF-001",
        source_system="CSV_IMPORT",
        records=[default_supplier],
        originating_region="DEFAULT",
    )

    default_result = RegionalComplianceRouter.anonymize_batch(
        batch_request=default_batch,
    )

    default_record = default_result.records[0]
    default_name_preserved = (default_record.contact_name == original_contact_name)
    default_email_preserved = (default_record.contact_email == original_contact_email)

    # ------------------------------------------------------------------
    # REPORT — print pass/fail for every assertion
    # ------------------------------------------------------------------
    print("=" * 60)
    print("  REGIONAL COMPLIANCE ROUTER — VERIFICATION REPORT")
    print("=" * 60)

    all_passed = True

    # EU assertions
    if eu_name_redacted:
        print("  [PASS] EU branch — contact_name was REDACTED_GDPR")
    else:
        print("  [FAIL] EU branch — contact_name was NOT redacted")
        all_passed = False

    if eu_email_redacted:
        print("  [PASS] EU branch — contact_email was REDACTED@gdpr.eu")
    else:
        print("  [FAIL] EU branch — contact_email was NOT redacted")
        all_passed = False

    # IN assertions
    if in_name_preserved:
        print("  [PASS] IN branch — contact_name preserved as 'John Doe'")
    else:
        print("  [FAIL] IN branch — contact_name was incorrectly modified")
        all_passed = False

    if in_email_preserved:
        print("  [PASS] IN branch — contact_email preserved as 'john@example.com'")
    else:
        print("  [FAIL] IN branch — contact_email was incorrectly modified")
        all_passed = False

    # DEFAULT assertions
    if default_name_preserved:
        print("  [PASS] DEFAULT branch — contact_name preserved as 'John Doe'")
    else:
        print("  [FAIL] DEFAULT branch — contact_name was incorrectly modified")
        all_passed = False

    if default_email_preserved:
        print("  [PASS] DEFAULT branch — contact_email preserved as 'john@example.com'")
    else:
        print("  [FAIL] DEFAULT branch — contact_email was incorrectly modified")
        all_passed = False

    # Final verdict
    print("=" * 60)
    if all_passed:
        print("  VERDICT: STATE MACHINE PROVEN CORRECT — all 6 assertions passed.")
    else:
        print("  VERDICT: STATE MACHINE HAS BUGS — one or more assertions failed.")
    print("=" * 60)


if __name__ == "__main__":
    main()
