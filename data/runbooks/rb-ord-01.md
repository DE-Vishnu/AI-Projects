---
runbook_id: RB-ORD-01
title: "Orders incremental ingestion recovery"
service: orders_ingestion
triggers:
  - "watermark_change"
  - "late_arriving_records"
  - "pipeline_lag"
  - "missing_orders"
---

# Orders incremental ingestion recovery

## When to use

Use this runbook for service `orders_ingestion` when one or more of these conditions apply:

- watermark_change
- late_arriving_records
- pipeline_lag
- missing_orders

## Pre-deployment and diagnostic checks

- Validate watermark lower and upper boundaries
- Check source-key uniqueness before MERGE
- Compare source and target counts for the replay window

## Rollback steps

1. Pause the affected ingestion job
2. Restore the previous watermark configuration
3. Replay the bounded time window after deduplication

## Rollback triggers

- Missing-record count exceeds agreed tolerance
- Duplicate-key count rises above baseline
- Pipeline lag exceeds the service SLO

## Operational note

Follow the service owner’s approved change procedure. Record evidence, timestamps and the release identifier when executing these steps.
