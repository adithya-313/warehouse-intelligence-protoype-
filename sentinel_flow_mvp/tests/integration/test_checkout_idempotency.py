"""
Integration tests for the POS Checkout transactional guards.

Beginner Note:
    These tests live in the ``integration/`` directory because they verify that
    TWO or more system components work correctly together. Specifically, they
    test the interaction between:
      1. The FastAPI route handler (pos_router.py).
      2. The Redis transactional guards (redis_client.py) — mocked via the
         shared conftest.py fixtures.
      3. The SHA-256 deterministic idempotency key generation.

    The autouse ``mock_redis_guards`` fixture from conftest.py patches ALL six
    Redis functions automatically so we don't need a real Redis server.

Focus Area: Idempotency & FEFO Saga — the two 409 Conflict scenarios.
    1. Duplicate checkout detection (SHA-256 hash collision).
    2. FEFO inventory lock expired (resource contention).

Every test follows the Arrange-Act-Assert (AAA) pattern:
    1. ARRANGE: Configure the mock Redis return values.
    2. ACT:     Send the POST request to /api/v1/pos/checkout.
    3. ASSERT:  Verify the HTTP 409 status and error message.
"""

import uuid


class TestCheckoutIdempotencyGuard:
    """
    Test Case 1: SHA-256 Idempotency Detection → 409 Conflict.

    Why does this matter?
        In a busy pharmacy, the cashier may accidentally double-click the
        "Pay" button. Without idempotency, the customer would be charged
        TWICE. The SHA-256 hash ensures that the EXACT same cart always
        produces the EXACT same hash, so the second click is rejected.

    How the SHA-256 flow works (ref: pos_router.py lines 303–336):
        1. The server sorts the cart items by batch_id.
        2. It builds a canonical JSON string from: tenant_id + items +
           payment_method + customer_phone + frontend_idempotency_key.
        3. It computes: hashlib.sha256(canonical_json.encode()).hexdigest().
        4. It calls is_duplicate_checkout_request(hash).
        5. If the hash already exists in Redis → 409 Conflict.
    """

    def test_duplicate_idempotency_hash_returns_409(
        self,
        client,
        mock_db_session,
        mock_redis_guards,
    ):
        """
        ARRANGE: Tell the Redis mock to pretend this checkout hash already
        exists (i.e., was already processed). This simulates the second
        click of a double-click scenario.

        ACT: Send a normal checkout POST request.

        ASSERT: 409 Conflict because the SHA-256 hash matched a previous
        checkout. The database must NOT be touched.
        """
        # =====================================================================
        # ARRANGE: Configure the idempotency guard to say "duplicate detected"
        # =====================================================================
        # The mock_redis_guards fixture patches is_duplicate_checkout_request
        # in the pos_router module. By default it returns False (not a duplicate).
        # We override it to return True for this test.
        mock_redis_guards["is_duplicate_checkout_request"].return_value = True

        # Reset the database call counters so we can prove they were never used.
        mock_db_session.add.reset_mock()
        mock_db_session.commit.reset_mock()
        mock_db_session.rollback.reset_mock()

        # =====================================================================
        # ACT: Send a checkout request identical to what the frontend would send
        # =====================================================================
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
            # The idempotency_key is the frontend's random UUID. The server
            # includes it in the SHA-256 hash as a "salt" so that even if two
            # different checkouts have identical items, they get different hashes.
            "idempotency_key": str(uuid.uuid4()),
            "customer_phone": "",
            "customer_name": "",
        }

        response = client.post("/api/v1/pos/checkout", json=checkout_payload)

        # =====================================================================
        # ASSERT: The duplicate checkout is rejected with 409 Conflict
        # =====================================================================
        # HTTP 409 means "Conflict" — the resource (this checkout) conflicts
        # with the current state of the server (it was already processed).
        assert response.status_code == 409, (
            f"Expected 409 Conflict for duplicate idempotency hash, "
            f"but got {response.status_code}. Response body: {response.text}"
        )

        # The error message must mention "duplicate" so the frontend can
        # display a human-readable explanation to the cashier.
        response_body = response.json()
        assert "duplicate" in response_body["detail"].lower(), (
            f"Error message should contain 'duplicate' to inform the cashier. "
            f"Got: {response_body['detail']}"
        )

        # CRITICAL SAFETY CHECK: No database work was done.
        # If the idempotency guard fires, the checkout must abort BEFORE
        # touching the database. Otherwise we waste DB connections and risk
        # partial writes.
        mock_db_session.add.assert_not_called()
        mock_db_session.commit.assert_not_called()
        mock_db_session.rollback.assert_not_called()


class TestCheckoutFefoLockGuard:
    """
    Test Case 2: FEFO Inventory Lock Expired → 409 Conflict.

    Why does this matter?
        When the cashier scans an item, the FEFO routing endpoint selects the
        best batch and creates a temporary Redis lock (60-second TTL). If the
        cashier takes too long to complete the checkout, the lock expires and
        another cashier might sell that batch. Without this check, the first
        cashier could complete a checkout for inventory that no longer exists.

    How the FEFO Saga works (ref: pos_router.py lines 306–391):
        1. GET /fefo-routing/{sku_id} selects the optimal batch and acquires
           a Redis lock via try_acquire_inventory_lock() with 60s TTL.
        2. POST /checkout verifies the lock via verify_inventory_lock_exists().
        3. If the lock expired (TTL elapsed or another checkout claimed it),
           the checkout is rejected with 409 Conflict.
    """

    def test_fefo_lock_expired_returns_409(
        self,
        client,
        mock_db_session,
        mock_redis_guards,
    ):
        """
        ARRANGE: Configure the FEFO lock verification mock to say "lock not
        found" (verify_inventory_lock_exists returns False). This simulates
        the scenario where the cashier took longer than 60 seconds to check out.

        ACT: Send a normal checkout POST request.

        ASSERT: 409 Conflict because the FEFO lock expired. The frontend
        must re-run FEFO routing to get a fresh lock on a (potentially
        different) batch.
        """
        # =====================================================================
        # ARRANGE: Make the lock verification say "this batch is no longer yours"
        # =====================================================================
        # By default, mock_redis_guards["verify_inventory_lock_exists"] returns
        # True (lock is valid). We override it to return False so the route
        # hits the lock-expired code path.
        mock_redis_guards["verify_inventory_lock_exists"].return_value = False

        # Reset database mocks to verify they are never touched when lock fails.
        mock_db_session.add.reset_mock()
        mock_db_session.commit.reset_mock()
        mock_db_session.rollback.reset_mock()

        # =====================================================================
        # ACT: Send a checkout request with items that have "expired" locks
        # =====================================================================
        checkout_payload = {
            "items": [
                {
                    "batch_id": "BATCH-002",
                    "sku_id": "SKU-002",
                    "name": "Amoxicillin 250mg",
                    "quantity": 1,
                    "price": 120.00,
                }
            ],
            "payment_method": "UPI",
            "idempotency_key": str(uuid.uuid4()),
            "customer_phone": "",
            "customer_name": "",
        }

        response = client.post("/api/v1/pos/checkout", json=checkout_payload)

        # =====================================================================
        # ASSERT: The expired FEFO lock is rejected with 409 Conflict
        # =====================================================================
        # HTTP 409 is the correct status for resource contention — this batch
        # is in conflict with another checkout process.
        assert response.status_code == 409, (
            f"Expected 409 Conflict for expired FEFO lock, "
            f"but got {response.status_code}. Response body: {response.text}"
        )

        # The error detail should tell the cashier to re-scan the item.
        response_body = response.json()
        assert "no longer reserved" in response_body["detail"].lower(), (
            f"Error message should mention 'no longer reserved' so the cashier "
            f"knows to re-scan. Got: {response_body['detail']}"
        )

        # CRITICAL SAFETY CHECK: No database work was done.
        mock_db_session.add.assert_not_called()
        mock_db_session.commit.assert_not_called()
        mock_db_session.rollback.assert_not_called()
