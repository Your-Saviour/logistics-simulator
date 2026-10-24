# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary users are inferred from the existing Logistics interface and design brief: dispatch coordinators and transport controllers operating an active simulation run. Fleet allocators and operations supervisors are secondary users.

## Product Purpose

The Logistics application coordinates simulated goods transfers from request through assignment, loading, departure, arrival, unloading, and receipt. Success means an operator can see what is moving, understand custody and timing, and issue only the next valid command without losing run context.

## Positioning

The application joins operational dispatch decisions to deterministic simulation time, epoch fencing, idempotent commands, provider boundaries, and a complete custody trail.

## Operating Context

Operators work inside a named simulation run with granted, requested, and committed time. They monitor vehicles, configured routes, transfers, pending commands, custody movements, service health, and audit records. Actions are permission-scoped and may become invalid when the run or epoch changes.

## Capabilities and Constraints

- Preserve the existing Svelte frontend, HTTP API, roles, field names, and transport lifecycle.
- Valid transfer actions are Assign, Load, Depart, Confirm arrival, Unload, and Confirm receipt.
- Transport requests contain route, SKU, quantity, and correlation ID.
- Retryable commands retain their original fields and idempotency key.
- Run controls, diagnostics, jobs, and audit data remain available but are secondary to dispatch work.
- Build and verification run only inside Docker.

## Evidence on Hand

The source of truth is the existing implementation in `apps/logistics/frontend/src/App.svelte`, `Transport.svelte`, `client.ts`, and `style.css`, plus its adjacent tests and backend contract. No logos, photography, testimonials, commercial claims, or customer data are present and none should be fabricated.

## Product Principles

- Put the next valid operational action close to the state that enables it.
- Keep status, custody, timing, and assignment visually distinct.
- Preserve entered command data across retryable failures.
- Make dense operational information scannable without hiding identifiers.
- Treat destructive run controls and low-level diagnostics as deliberate secondary tasks.

## Accessibility & Inclusion

Use semantic controls and tables, visible keyboard focus, non-colour status cues, readable contrast, and layouts that remain operable at narrow viewport widths.
