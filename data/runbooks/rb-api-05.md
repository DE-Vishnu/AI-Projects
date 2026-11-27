---
runbook_id: RB-API-05
title: "Export API rate-limit recovery"
service: saas_export_connector
triggers:
  - "429"
  - "rate_limit"
  - "retry"
  - "connector_lag"
---

# Export API rate-limit recovery

## When to use

Use this runbook for service `saas_export_connector` when one or more of these conditions apply:

- 429
- rate_limit
- retry
- connector_lag

## Pre-deployment and diagnostic checks

- Verify Retry-After handling
- Check exponential backoff and jitter
- Inspect quota consumption and backlog

## Rollback steps

1. Restore the previous bounded polling rate
2. Pause non-critical export jobs
3. Resume in controlled batches

## Rollback triggers

- Repeated 429 responses
- Connector lag breaches freshness SLO

## Operational note

Follow the service owner’s approved change procedure. Record evidence, timestamps and the release identifier when executing these steps.
