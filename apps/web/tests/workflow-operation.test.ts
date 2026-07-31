import assert from "node:assert/strict";
import test from "node:test";

import {
  MAX_OUTSTANDING_PER_WORKFLOW_OPERATION,
  trackedWorkflowOperationCount,
  withWorkflowOperationLock,
} from "../lib/workflow-operation";
import { RequestRateLimitError } from "../lib/request-rate-limit";

test("completed workflow operation locks are removed", async () => {
  for (let index = 0; index < 100; index += 1) {
    const value = await withWorkflowOperationLock(
      `00000000-0000-4000-8000-${index.toString().padStart(12, "0")}`,
      async () => index,
    );
    assert.equal(value, index);
  }
  assert.equal(trackedWorkflowOperationCount(), 0);
});

test("same workflow operation remains serialized and then releases", async () => {
  const order: string[] = [];
  let releaseFirst: (() => void) | undefined;
  const firstGate = new Promise<void>((resolve) => {
    releaseFirst = resolve;
  });

  const first = withWorkflowOperationLock("shared-operation", async () => {
    order.push("first-start");
    await firstGate;
    order.push("first-end");
  });
  const second = withWorkflowOperationLock("shared-operation", async () => {
    order.push("second");
  });

  await Promise.resolve();
  assert.deepEqual(order, ["first-start"]);
  releaseFirst?.();
  await Promise.all([first, second]);
  assert.deepEqual(order, ["first-start", "first-end", "second"]);
  assert.equal(trackedWorkflowOperationCount(), 0);
});

test("same workflow operation has a bounded waiter queue", async () => {
  let releaseFirst: (() => void) | undefined;
  const firstGate = new Promise<void>((resolve) => {
    releaseFirst = resolve;
  });
  let actionCalls = 0;
  const queued = Array.from(
    { length: MAX_OUTSTANDING_PER_WORKFLOW_OPERATION },
    (_, index) =>
      withWorkflowOperationLock("bounded-operation", async () => {
        actionCalls += 1;
        if (index === 0) {
          await firstGate;
        }
      }),
  );

  await Promise.resolve();
  await assert.rejects(
    withWorkflowOperationLock("bounded-operation", async () => {
      actionCalls += 1;
    }),
    (error: unknown) =>
      error instanceof RequestRateLimitError &&
      error.code === "workflow_operation_queue_full" &&
      error.retryAfterSeconds === 1,
  );
  assert.equal(actionCalls, 1);

  releaseFirst?.();
  await Promise.all(queued);
  assert.equal(
    actionCalls,
    MAX_OUTSTANDING_PER_WORKFLOW_OPERATION,
  );
  assert.equal(trackedWorkflowOperationCount(), 0);
});
