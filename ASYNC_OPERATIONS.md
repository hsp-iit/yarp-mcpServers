# Asynchronous operations

The server-side convention represents long-running YARP activity as a durable MCP
resource. Resource subscription events tell clients when to refetch it; polling
provides recovery when events are missed.

## Public contract

The accepted-work result is `StartOperationResult`:

```text
success, operation_id, operation_type, status, status_uri,
poll_interval_ms, message
```

The resource returns `OperationSnapshot`:

```text
operation_id, operation_type, status, status_message, progress,
created_at, updated_at, poll_interval_ms, status_uri, details,
result, error, revision
```

Statuses are `working`, `completed`, `failed`, and `cancelled`. Terminal records
cannot transition to another state. Progress is optional and constrained to
`0.0 <= progress <= 1.0`. Every committed change increments `revision`.

## Implementation recipe

Inside a tool that starts background work:

```python
accepted = self.navigation.gotoTargetByAbsoluteLocation(target)
if not accepted:
    return {"success": False, "error": "Navigation rejected the target"}

operation = await self.operation_registry.create(
    "navigation_absolute",
    status_message="Navigation accepted",
    details={"target": target_as_dict},
    poll_interval_ms=500,
)
await self._start_operation_task(
    operation,
    self._navigation_monitor_loop(operation.operation_id),
)
return StartOperationResult(
    operation_id=operation.operation_id,
    operation_type=operation.operation_type,
    status_uri=operation.status_uri,
    poll_interval_ms=operation.poll_interval_ms,
    message="Navigation accepted",
)
```

The worker updates only through the registry:

```python
await self.operation_registry.update(
    operation_id,
    status="working",
    status_message="Robot is moving",
    progress=0.5,
    details={"navigation_status": "moving"},
)
```

On success, set `status="completed"` and `result`. On a domain failure, set
`status="failed"` and a structured `error`. On `asyncio.CancelledError`, record
`cancelled` and re-raise. Never publish before `update()` has stored the state;
the registry enforces commit-before-publish.

Monitor loops invoke synchronous YARP bindings through `_call_yarp()`. This moves
the potentially blocking network call off the MCP event loop while serializing
access to the device interface. Resource reads, subscription delivery, and
cancellation therefore remain responsive while a YARP wrapper is awaiting its
reply.

Navigation polls at 250 ms. Besides the explicit `goal_reached` state, an
active-state-to-`idle` transition is treated as successful completion because
some navigation implementations do not retain `goal_reached` long enough for a
polling observer to see it. An initial `idle` state is not considered complete.

## Cancellation and cleanup

`cancel_operation` cancels the attached asyncio task and commits `cancelled`.
Server lifespan calls registry shutdown, which cancels and awaits every retained
worker. A concrete cleanup tool should also call `_cleanup_operations()` before
closing YARP interfaces.

Navigation overrides the cancellation hook: it calls YARP `stopNavigation()`
before cancelling the monitor. If YARP rejects the stop request, the MCP
cancellation fails and the operation remains active. Calling the explicit
`stop_navigation` tool also cancels every active navigation operation after the
robot accepts the stop command. Cancelling a battery monitor has no physical
side effect; it only stops observation.

## Retention

Terminal snapshots remain readable for 30 minutes by default, allowing a client
to recover after a temporary disconnect. The operations base runs a maintenance
task every minute to remove expired terminal records. Active operations are never
removed by expiry.

## What is intentionally absent

- No custom `notifications/tasks/status` JSON-RPC method: it is not a portable
  stable contract for this implementation.
- No server-held client-session registry: the SDK subscription bus owns delivery.
- No progress tokens for detached work: request-scoped progress cannot replace a
  resource that must remain queryable after the initiating tool call returns.
- No experimental MCP Tasks dependency: operation resources work with the stable
  resource and subscription surface implemented by the selected SDK release.
