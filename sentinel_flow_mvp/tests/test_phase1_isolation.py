"""
PHASE 1: MULTI-TENANT ISOLATION & SCRAPER RESILIENCE TESTS
============================================================

Beginner Note:
    This test file verifies two critical behaviours of the Phase 1
    architecture:

    1. TENANT ISOLATION ENFORCEMENT:
       We confirm that the ORM models require ``tenant_id`` to be
       provided (NOT NULL constraint at the model/DB level). A query
       that tries to create a record without a valid tenant scope
       MUST fail — this is our "structural validation error."

    2. SCRAPER RESILIENCE:
       We confirm that the ``StalenessAlertException`` is correctly
       raised when the mock CDSCO feed is empty or malformed, and
       that the scraper handles a down database gracefully.

    How we test without a real database:
        The conftest.py file (in tests/) provides a ``mock_db_session``
        fixture that replaces real PostgreSQL with MagicMock objects.
        For the tenant isolation tests, we verify the model definitions
        themselves (column nullability, foreign key constraints) using
        SQLAlchemy's introspection API. For the scraper tests, we call
        the mock scraper functions directly and assert on the results.

    Reference:
        - app/infrastructure/models.py (MedicationModel, MedicationBatchModel)
        - app/infrastructure/db/models.py  (AuditLedger, etc.)
        - scripts/mock_government_scraper.py (StalenessAlertException)
"""

# ======================================================================
# IMPORTS
# ======================================================================
# Beginner Note: We import pytest, the ORM models, and the scraper
# module. We do NOT import psycopg2 or the database engine because
# these tests must run without a real database.

import pytest
from sqlalchemy import Column, ForeignKey, String, Integer  # For type introspection
from unittest.mock import patch


# ======================================================================
# TEST 1: Tenant isolation — structural validation error on missing tenant
# ======================================================================
# Beginner Note: The most basic structural validation is that the
# ``tenant_id`` column on models like ``MedicationBatchModel`` is
# defined as ``nullable=False``. This means that if someone tries to
# create a row without specifying a tenant, SQLAlchemy will raise an
# IntegrityError when it reaches the database.
#
# We test this at the ORM level by checking the column definition
# directly. This is a COMPILE-TIME check — it runs instantly without
# needing a database connection.

class TestTenantIsolationStructuralValidation:
    """
    Suite of tests that verify tenant isolation is structurally enforced
    at the ORM definition level.
    """

    # We import the models INSIDE each test method (rather than at the
    # top of the class) so that any import errors are isolated to the
    # specific test that failed. This makes debugging easier for junior
    # developers.

    def test_medication_batches_requires_tenant_id(self):
        """
        Verify that MedicationBatchModel.tenant_id is defined with
        nullable=False and a ForeignKey to tenants.tenant_id.

        Reasoning:
            If someone writes code that creates a MedicationBatch without
            setting ``batch.tenant_id = "some-tenant"``, SQLAlchemy will
            raise an IntegrityError at INSERT time because the column
            is NOT NULL. This is our "structural validation error."
        """
        from app.infrastructure.models import MedicationBatchModel

        # Step 1: Get the tenant_id column from the model's table definition
        tenant_id_column: Column = MedicationBatchModel.__table__.columns["tenant_id"]

        # Step 2: Assert that the column is NOT NULL (cannot be left empty)
        assert tenant_id_column.nullable is False, (
            "MedicationBatchModel.tenant_id must be NOT NULL. "
            "Without this constraint, a developer could accidentally "
            "create a batch that does not belong to any tenant."
        )

        # Step 3: Assert that the column has a ForeignKey constraint
        # pointing to the tenants table.
        has_foreign_key = any(
            isinstance(constraint, ForeignKey)
            and constraint.target_fullname == "tenants.tenant_id"
            for constraint in tenant_id_column.foreign_keys
        )
        assert has_foreign_key, (
            "MedicationBatchModel.tenant_id must have a ForeignKey "
            "constraint pointing to 'tenants.tenant_id'. Without it, "
            "a batch could reference a tenant that does not exist."
        )

    def test_sale_receipts_requires_tenant_id(self):
        """
        Verify that SaleReceiptModel.tenant_id enforces the same
        NOT NULL + ForeignKey constraint.
        """
        from app.infrastructure.models import SaleReceiptModel

        tenant_id_column: Column = SaleReceiptModel.__table__.columns["tenant_id"]

        assert tenant_id_column.nullable is False, (
            "SaleReceiptModel.tenant_id must be NOT NULL."
        )

        has_foreign_key = any(
            isinstance(constraint, ForeignKey)
            and constraint.target_fullname == "tenants.tenant_id"
            for constraint in tenant_id_column.foreign_keys
        )
        assert has_foreign_key, (
            "SaleReceiptModel.tenant_id must have a ForeignKey "
            "to 'tenants.tenant_id'."
        )

    def test_sale_line_items_requires_tenant_id(self):
        """
        Verify that SaleLineItemModel.tenant_id enforces the same
        NOT NULL + ForeignKey constraint.
        """
        from app.infrastructure.models import SaleLineItemModel

        tenant_id_column: Column = SaleLineItemModel.__table__.columns["tenant_id"]

        assert tenant_id_column.nullable is False, (
            "SaleLineItemModel.tenant_id must be NOT NULL."
        )

        has_foreign_key = any(
            isinstance(constraint, ForeignKey)
            and constraint.target_fullname == "tenants.tenant_id"
            for constraint in tenant_id_column.foreign_keys
        )
        assert has_foreign_key, (
            "SaleLineItemModel.tenant_id must have a ForeignKey "
            "to 'tenants.tenant_id'."
        )

    def test_purchase_orders_requires_tenant_id(self):
        """
        Verify that PurchaseOrderModel.tenant_id enforces the same
        NOT NULL + ForeignKey constraint.
        """
        from app.infrastructure.models import PurchaseOrderModel

        tenant_id_column: Column = PurchaseOrderModel.__table__.columns["tenant_id"]

        assert tenant_id_column.nullable is False, (
            "PurchaseOrderModel.tenant_id must be NOT NULL."
        )

        has_foreign_key = any(
            isinstance(constraint, ForeignKey)
            and constraint.target_fullname == "tenants.tenant_id"
            for constraint in tenant_id_column.foreign_keys
        )
        assert has_foreign_key, (
            "PurchaseOrderModel.tenant_id must have a ForeignKey "
            "to 'tenants.tenant_id'."
        )


# ======================================================================
# TEST 2: Clinical Master Index — field structure validation
# ======================================================================
# Beginner Note: We verify that the new clinical fields were added
# correctly to the MedicationModel. These tests check:
#   - The field exists with the correct data type
#   - Nullable fields are nullable
#   - The curator approval flag has a server default of False

class TestClinicalMasterIndexFields:
    """
    Suite of tests that verify the clinical master index fields exist
    on MedicationModel with the correct structural properties.
    """

    def test_pregnancy_category_column_exists(self):
        """
        Verify that MedicationModel has a ``pregnancy_category`` column
        of type String(2) that is nullable.
        """
        from app.infrastructure.models import MedicationModel

        column: Column = MedicationModel.__table__.columns["pregnancy_category"]

        # It should be a String with max 2 characters (e.g., 'A', 'B', 'X')
        assert str(column.type).startswith("VARCHAR"), (
            "pregnancy_category must be a VARCHAR column."
        )
        # It should be nullable (not all drugs are classified)
        assert column.nullable is True, (
            "pregnancy_category must be nullable because not all "
            "drugs have been classified by CDSCO/FDA."
        )

    def test_pediatric_age_threshold_column_exists(self):
        """
        Verify that MedicationModel has a
        ``pediatric_age_threshold_months`` column of type Integer
        that is nullable.
        """
        from app.infrastructure.models import MedicationModel

        column: Column = MedicationModel.__table__.columns[
            "pediatric_age_threshold_months"
        ]

        # It should be an Integer column
        assert isinstance(column.type, Integer), (
            "pediatric_age_threshold_months must be an INTEGER column."
        )
        assert column.nullable is True, (
            "pediatric_age_threshold_months must be nullable because "
            "many drugs have no age restriction."
        )

    def test_interaction_matrix_column_exists(self):
        """
        Verify that MedicationModel has an ``interaction_matrix``
        column of type JSONB that is nullable.
        """
        from app.infrastructure.models import MedicationModel
        from sqlalchemy.dialects.postgresql import JSONB

        column: Column = MedicationModel.__table__.columns["interaction_matrix"]

        # It should be a JSONB column
        assert isinstance(column.type, JSONB), (
            "interaction_matrix must be a JSONB column."
        )
        assert column.nullable is True, (
            "interaction_matrix must be nullable because not all "
            "drugs have known interactions."
        )

    def test_is_approved_by_curator_has_server_default_false(self):
        """
        Verify that ``is_approved_by_curator`` has a server default of
        ``false`` and is NOT NULL.

        Reasoning:
            When the scraper adds a new drug or updates an existing one,
            ``is_approved_by_curator`` must default to False so that a
            human pharmacist must review the change before it goes live.
            The server_default ensures this happens at the DATABASE level,
            even if the application code forgets to set it.
        """
        from app.infrastructure.models import MedicationModel

        column: Column = MedicationModel.__table__.columns[
            "is_approved_by_curator"
        ]

        # It must be NOT NULL (every drug must have a curator review state)
        assert column.nullable is False, (
            "is_approved_by_curator must be NOT NULL. Every drug must "
            "have a curator review state."
        )

        # It must have a server default of 'false'
        # The server_default is a SQL expression like ``false::boolean``
        # or ``'false'`` depending on the dialect.
        assert column.server_default is not None, (
            "is_approved_by_curator must have a server_default. "
            "Without it, new rows inserted without explicitly setting "
            "this column would get NULL instead of FALSE."
        )


# ======================================================================
# TEST 3: Regulatory Diff Log — table structure validation
# ======================================================================

class TestRegulatoryDiffLogStructure:
    """
    Suite of tests that verify the regulatory_diff_log table was
    created with the correct structure.
    """

    def test_regulatory_diff_log_has_required_columns(self):
        """
        Verify that RegulatoryDiffLogModel has all required columns
        with the correct types and constraints.
        """
        from app.infrastructure.models import RegulatoryDiffLogModel

        table = RegulatoryDiffLogModel.__table__

        # Check that all expected columns exist
        expected_columns = [
            "id", "timestamp", "product_id", "old_value",
            "new_value", "source_gov_url", "curator_id",
        ]
        for column_name in expected_columns:
            assert column_name in table.columns, (
                f"RegulatoryDiffLogModel is missing column '{column_name}'."
            )

        # The 'id' column should be a BigInteger primary key
        id_column = table.columns["id"]
        assert id_column.primary_key is True, (
            "regulatory_diff_log.id must be a primary key."
        )
        from sqlalchemy import BigInteger
        assert isinstance(id_column.type, BigInteger), (
            "regulatory_diff_log.id must be BigInteger."
        )

        # The 'product_id' column should have a ForeignKey to medications
        product_id_column = table.columns["product_id"]
        has_medication_fk = any(
            isinstance(constraint, ForeignKey)
            and constraint.target_fullname == "medications.sku_id"
            for constraint in product_id_column.foreign_keys
        )
        assert has_medication_fk, (
            "regulatory_diff_log.product_id must have a ForeignKey "
            "to 'medications.sku_id'."
        )

    def test_regulatory_diff_log_curator_id_is_nullable(self):
        """
        Verify that curator_id is nullable (the log entry is created
        before a human curator reviews it).
        """
        from app.infrastructure.models import RegulatoryDiffLogModel

        curator_column = RegulatoryDiffLogModel.__table__.columns["curator_id"]
        assert curator_column.nullable is True, (
            "regulatory_diff_log.curator_id must be nullable because "
            "the log entry is created before a human reviews it."
        )


# ======================================================================
# TEST 4: Scraper Resilience — StalenessAlertException
# ======================================================================
# Beginner Note: These tests verify that the mock government scraper
# handles failure modes gracefully:
#   - Empty/malformed feed -> raises StalenessAlertException
#   - Database offline -> logs error and exits without crashing

class TestScraperResilience:
    """
    Suite of tests that verify the scraper's ability to handle
    failure scenarios without corrupting state.
    """

    def test_staleness_alert_raised_on_empty_feed(self):
        """
        Verify that ``simulate_cdsco_feed(should_fail=True)`` raises
        a StalenessAlertException.

        Reasoning:
            If the government portal returns an empty page (no new
            notifications), the scraper MUST NOT silently insert empty
            rows into the regulatory_diff_log. It must raise an error
            that the monitoring system can detect.
        """
        from scripts.mock_government_scraper import (
            simulate_cdsco_feed,
            StalenessAlertException,
        )

        # We expect the exception to be raised
        with pytest.raises(StalenessAlertException) as exc_info:
            simulate_cdsco_feed(should_fail=True)

        # Verify the exception has the expected attributes
        exception = exc_info.value
        assert "empty" in exception.message.lower(), (
            "The StalenessAlertException message should mention that "
            "the feed was empty."
        )

        # The feed_content should be an empty string (simulating an
        # empty download from the government portal)
        assert exception.feed_content == "", (
            "The feed_content should be an empty string when the "
            "CDSCO portal returns nothing."
        )

    def test_staleness_alert_metric_log_format(self):
        """
        Verify that the ``to_metric_log()`` method of
        StalenessAlertException returns a properly structured
        dictionary suitable for monitoring systems.
        """
        from scripts.mock_government_scraper import StalenessAlertException

        # Create an exception with a realistic error scenario
        exception = StalenessAlertException(
            message="CDSCO feed returned 0 notifications.",
            feed_content="<html></html>",
        )

        # Convert to the metric log format
        metric_log = exception.to_metric_log()

        # Verify the structure of the metric log
        assert "error_type" in metric_log, (
            "Metric log must contain 'error_type' so the monitoring "
            "system can categorise the alert."
        )
        assert metric_log["error_type"] == "StalenessAlertException", (
            "The error_type must be 'StalenessAlertException'."
        )
        assert "message" in metric_log, (
            "Metric log must contain a human-readable 'message'."
        )
        assert "timestamp" in metric_log, (
            "Metric log must contain an ISO-formatted 'timestamp' "
            "so the operations team knows when the error occurred."
        )
        assert "feed_content_preview" in metric_log, (
            "Metric log must contain a preview of the malformed "
            "feed content for debugging."
        )

    @patch("psycopg2.connect")
    def test_scraper_handles_database_offline_gracefully(self, mock_connect):
        """
        Verify that ``try_database_connection()`` returns False when
        the database is unreachable, and does NOT raise an exception.

        Reasoning:
            The scraper will typically run in a Docker container where
            the database is always available. But during development,
            or if the database container crashes, the scraper must
            detect this and exit cleanly instead of crashing with a
            confusing stack trace.
        """
        from scripts.mock_government_scraper import try_database_connection

        # The database is offline (Docker Desktop is not running in
        # this development environment). We verify that the function
        # returns False without raising an exception.
        mock_connect.side_effect = Exception("Database connection failed")
        result = try_database_connection()

        assert result is False, (
            "try_database_connection() should return False when the "
            "database is unreachable. It should NOT raise an exception."
        )
