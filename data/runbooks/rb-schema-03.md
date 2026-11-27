---
runbook_id: RB-SCHEMA-03
title: "Schema and API contract compatibility"
service: customer_profile_api
triggers:
  - "schema_change"
  - "api_contract_change"
  - "consumer_failure"
---

# Schema and API contract compatibility

## When to use

Use this runbook for service `customer_profile_api` when one or more of these conditions apply:

- schema_change
- api_contract_change
- consumer_failure

## Pre-deployment and diagnostic checks

- Run consumer-driven contract tests
- Validate nullable and required fields
- Confirm downstream consumer adoption

## Rollback steps

1. Restore the previous response contract
2. Enable compatibility mapping
3. Replay failed events where applicable

## Rollback triggers

- Consumer rejection rate increases
- Dead-letter queue depth crosses threshold

## Operational note

Follow the service owner’s approved change procedure. Record evidence, timestamps and the release identifier when executing these steps.
