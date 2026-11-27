---
runbook_id: RB-PAY-02
title: "Payment gateway credential rotation"
service: payments_api
triggers:
  - "authentication_change"
  - "token_refresh"
  - "authorization_error"
---

# Payment gateway credential rotation

## When to use

Use this runbook for service `payments_api` when one or more of these conditions apply:

- authentication_change
- token_refresh
- authorization_error

## Pre-deployment and diagnostic checks

- Verify token refresh on all worker pools
- Validate secret version and expiry
- Run a synthetic authorization transaction

## Rollback steps

1. Restore previous secret version
2. Restart workers with stale credentials
3. Verify authorization success rate

## Rollback triggers

- Authorization failures breach the error budget
- Token refresh failures persist after retry

## Operational note

Follow the service owner’s approved change procedure. Record evidence, timestamps and the release identifier when executing these steps.
