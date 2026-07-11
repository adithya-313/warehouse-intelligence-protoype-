"""
End-to-end tests for the POS Checkout endpoint (POST /api/v1/pos/checkout).

Focus Area: Transactional Core — Idempotency Guards.

Beginner Note: These tests prove that our checkout route correctly handles
duplicate requests. The most important test is the Idempotency Test because
it prevents the nightmare scenario of a customer being charged twice when
the pharmacist accidentally double-clicks "Submit".

Every test follows the Arrange-Act-Assert (AAA) pattern:
  1. ARRANGE: Set up the test data and configure mocks.
  2. ACT:     Send the HTTP request to the endpoint.
  3. ASSERT:  Verify the response status code and body.
"""

import uuid
from unittest.mock import MagicMock, PropertyMock


class TestPosCheckoutSuccess:
    """
    Test Case 1: Successful Checkout (Happy Path).

    Verifies that a valid checkout request with correctly mocked inventory
    and patient lookup returns a 200 OK with a receipt_id.
    """

    def test_successful_checkout_returns_200_and_receipt_id(
        self,
        client,
        mock_db_session,
        mock_redis_guards,
    ):
        """
        ARRANGE: Configure the mock database to simulate:
          1. Patient lookup returns None (new customer — no existing record).
          2. Batch inventory lookup returns a batch with sufficient stock.

        ACT: Send a POST request with a valid cart containing one item.

        ASSERT: The response is 200 OK and contains a receipt_id.
        """
        # ==================================================================
        # ARRANGE: Configure mock database to simulate inventory state
        # ==================================================================

        # --- Patient Lookup: Simulate "no existing patient" ---
        # When the route calls db.query(Patient).filter(...).first(),
        # it should return None so the route creates a new patient record.
        mock_patient_query = MagicMock()
        mock_patient_filter = MagicMock()
        mock_patient_filter.first.return_value = None
        mock_patient_query.filter.return_value = mock_patient_filter
        mock_db_session.query.return_value = mock_patient_query

        # --- Batch Inventory: Simulate an existing batch with stock ---
        # When the route calls db.query(MedicationBatchModel).filter(...)
        # .with_for_update().first(), it should return a batch with
        # available_quantity >= the requested quantity.
        mock_batch = MagicMock()
        mock_batch.batch_id = "BATCH-001"
        mock_batch.sku_id = "SKU-001"
        mock_batch.available_quantity = 50  # Sufficient stock
        mock_batch.max_retail_price = 45.00
        mock_batch.expiry_date = None  # Not needed for checkout flow

        mock_batch_query = MagicMock()
        mock_batch_filter = MagicMock()
        mock_batch_filter.with_for_update.return_value = mock_batch_filter
        mock_batch_filter.first.return_value = mock_batch
        mock_batch_query.filter.return_value = mock_batch_filter

        # We need to return the batch query only when MedicationBatchModel is queried.
        # We set up a side_effect on the main query mock that returns different
        # query builders depending on which model is being queried.
        def query_side_effect(model):
            # Import models inside the side_effect to avoid circular imports
            from app.infrastructure.models import MedicationBatchModel, Patient
            if model == MedicationBatchModel:
                return mock_batch_query
            return mock_patient_query

        mock_db_session.query.side_effect = query_side_effect

        # ==================================================================
        # ACT: Send the checkout request
        # ==================================================================
        checkout_payload = {
            "items": [
                {
                    "batch_id": "BATCH-001",
                    "sku_id": "SKU-001",
                    "name": "Paracetamol 500mg",
                    "quantity": 2,
                    "price": 45.00,
                }
            ],
            "payment_method": "CASH",
            "idempotency_key": str(uuid.uuid4()),
            "customer_phone": "",
            "customer_name": "",
        }

        response = client.post("/api/v1/pos/checkout", json=checkout_payload)

        # ==================================================================
        # ASSERT: Verify the response
        # ==================================================================
        assert response.status_code == 200, (
            f"Expected 200 OK but got {response.status_code}. "
            f"Response body: {response.text}"
        )

        response_data = response.json()
        assert "receipt_id" in response_data, (
            "Checkout response must contain a receipt_id."
        )
        assert response_data["message"] == "Checkout completed successfully and outbox event registered."

        # Verify the idempotency guard was actually called
        mock_redis_guards["is_duplicate_checkout_request"].assert_called_once()


class TestPosCheckoutIdempotency:
    """
    Test Case 2: Idempotency Conflict (409).

    Verifies that sending the SAME idempotency_key a second time results
    in a 409 Conflict response. This is the most important safety test
    because it prevents double-charging the customer.
    """

    def test_duplicate_idempotency_key_returns_409(
        self,
        client,
        mock_db_session,
        mock_redis_guards,
    ):
        """
        ARRANGE: Configure the Redis mock to simulate that the idempotency
        key ALREADY EXISTS (is_duplicate_checkout_request returns True).

        ACT: Send a checkout request with ANY idempotency_key.

        ASSERT: The response is 409 Conflict because the key is a duplicate.
        The database transaction functions should NEVER be called.
        """
        # ==================================================================
        # ARRANGE: Make the idempotency guard say "this is a duplicate"
        # ==================================================================
        mock_redis_guards["is_duplicate_checkout_request"].return_value = True

        # Reset the database mocks to verify they are never touched
        mock_db_session.add.reset_mock()
        mock_db_session.commit.reset_mock()
        mock_db_session.rollback.reset_mock()

        # ==================================================================
        # ACT: Send a checkout request
        # ==================================================================
        # Note: The idempotency_key value doesn't matter here because the
        # mock always returns True (duplicate) regardless of the input.
        checkout_payload = {
            "items": [
                {
                    "batch_id": "BATCH-001",
                    "sku_id": "SKU-001",
                    "name": "Paracetamol 500mg",
                    "quantity": 2,
                    "price": 45.00,
                }
            ],
            "payment_method": "UPI",
            "idempotency_key": "already-used-key-12345",
            "customer_phone": "",
            "customer_name": "",
        }

        response = client.post("/api/v1/pos/checkout", json=checkout_payload)

        # ==================================================================
        # ASSERT: 409 Conflict + no database work was done
        # ==================================================================
        assert response.status_code == 409, (
            f"Expected 409 Conflict for duplicate idempotency key, "
            f"but got {response.status_code}. Response: {response.text}"
        )

        response_data = response.json()
        assert "duplicate" in response_data["detail"].lower(), (
            f"Error detail should mention 'duplicate'. Got: {response_data['detail']}"
        )

        # Critical assertion: The database was NEVER touched.
        # If the route does any DB work after detecting a duplicate, that is
        # a wasted database call and a potential security issue.
        mock_db_session.add.assert_not_called()
        mock_db_session.commit.assert_not_called()
        mock_db_session.rollback.assert_not_called()
