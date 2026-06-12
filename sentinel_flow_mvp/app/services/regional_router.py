"""Regional Compliance Router — Aegis State Machine for PII Redaction.

This module implements a strict state-machine that inspects the
`originating_region` field on every incoming `BatchIngestionRequest`
and applies the appropriate data-privacy transformations BEFORE the
payload reaches the Celery async queue.

Domain-Driven Design context:
- The compliance boundary is the FIRST gate data passes through.
- Each region is an explicit state with its own mutation rules.
- Adding a new region means adding a new `elif` branch here.
"""

from app.domain.schemas import BatchIngestionRequest, SupplierRecord


class RegionalComplianceRouter:
    """Stateless router that applies region-specific PII redaction rules.

    This class contains NO instance state. It is implemented as a
    collection of static methods so that it can be called directly
    without instantiation overhead at ingestion time.
    """

    @staticmethod
    def anonymize_batch(
        batch_request: BatchIngestionRequest,
    ) -> BatchIngestionRequest:
        """Inspect the originating region and redact PII accordingly.

        The state machine branches on `batch_request.originating_region`:

            "EU"  → Redact all contact_name and contact_email fields
                     (GDPR Article 5(1)(c) — data minimisation).
            "IN"  → Leave all PII intact
                     (DPDP Act early-stage provisions for this dataset).
            DEFAULT → Leave all PII intact
                      (no compliance obligation identified).

        Args:
            batch_request: The validated ingestion payload with PII fields.

        Returns:
            A new `BatchIngestionRequest` with PII redacted (if applicable)
            but all other fields completely unchanged.
        """
        detected_region = batch_request.originating_region

        # ------------------------------------------------------------------
        # STATE: EU — General Data Protection Regulation (GDPR)
        # Action: Force-redact all PII fields to satisfy data minimisation.
        # ------------------------------------------------------------------
        if detected_region == "EU":

            redacted_records = []
            for each_record in batch_request.records:

                redacted_supplier = SupplierRecord(
                    supplier_id=each_record.supplier_id,
                    timestamp=each_record.timestamp,
                    inventory_count=each_record.inventory_count,
                    delivery_delay_days=each_record.delivery_delay_days,
                    contact_name="REDACTED_GDPR",
                    contact_email="REDACTED@gdpr.eu",
                )
                redacted_records.append(redacted_supplier)

            redacted_batch = BatchIngestionRequest(
                batch_identifier=batch_request.batch_identifier,
                source_system=batch_request.source_system,
                records=redacted_records,
                originating_region=batch_request.originating_region,
            )

            return redacted_batch

        # ------------------------------------------------------------------
        # STATE: IN — Digital Personal Data Protection Act (DPDP)
        # Action: Leave all PII intact per early-stage dataset provisions.
        # ------------------------------------------------------------------
        elif detected_region == "IN":

            intact_records = []
            for each_record in batch_request.records:

                intact_supplier = SupplierRecord(
                    supplier_id=each_record.supplier_id,
                    timestamp=each_record.timestamp,
                    inventory_count=each_record.inventory_count,
                    delivery_delay_days=each_record.delivery_delay_days,
                    contact_name=each_record.contact_name,
                    contact_email=each_record.contact_email,
                )
                intact_records.append(intact_supplier)

            intact_batch = BatchIngestionRequest(
                batch_identifier=batch_request.batch_identifier,
                source_system=batch_request.source_system,
                records=intact_records,
                originating_region=batch_request.originating_region,
            )

            return intact_batch

        # ------------------------------------------------------------------
        # STATE: DEFAULT (any unrecognised region)
        # Action: Leave all PII intact (no compliance obligation identified).
        # ------------------------------------------------------------------
        else:

            default_records = []
            for each_record in batch_request.records:

                default_supplier = SupplierRecord(
                    supplier_id=each_record.supplier_id,
                    timestamp=each_record.timestamp,
                    inventory_count=each_record.inventory_count,
                    delivery_delay_days=each_record.delivery_delay_days,
                    contact_name=each_record.contact_name,
                    contact_email=each_record.contact_email,
                )
                default_records.append(default_supplier)

            default_batch = BatchIngestionRequest(
                batch_identifier=batch_request.batch_identifier,
                source_system=batch_request.source_system,
                records=default_records,
                originating_region=batch_request.originating_region,
            )

            return default_batch
