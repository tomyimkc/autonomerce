import { RequestRateLimitError } from "./request-rate-limit";

interface OperationQueue {
  tail: Promise<void>;
  outstanding: number;
}

const operationQueues = new Map<string, OperationQueue>();
const MAX_TRACKED_WORKFLOW_OPERATIONS = 1_024;
export const MAX_OUTSTANDING_PER_WORKFLOW_OPERATION = 32;

export function trackedWorkflowOperationCount(): number {
  return operationQueues.size;
}

export async function withWorkflowOperationLock<T>(
  operationId: string,
  action: () => Promise<T>,
): Promise<T> {
  const existing = operationQueues.get(operationId);
  if (
    !existing &&
    operationQueues.size >= MAX_TRACKED_WORKFLOW_OPERATIONS
  ) {
    throw new RequestRateLimitError(
      "Too many distinct workflow operations are active. Wait before retrying.",
      1,
      "workflow_operation_capacity_exceeded",
    );
  }
  if (
    existing &&
    existing.outstanding >= MAX_OUTSTANDING_PER_WORKFLOW_OPERATION
  ) {
    throw new RequestRateLimitError(
      "Too many requests are queued for this workflow operation. Wait before retrying.",
      1,
      "workflow_operation_queue_full",
    );
  }
  const previous = existing?.tail ?? Promise.resolve();
  let release: (() => void) | undefined;
  const current = new Promise<void>((resolve) => {
    release = resolve;
  });
  const tail = previous.then(() => current);
  const queue = existing ?? { tail, outstanding: 0 };
  queue.tail = tail;
  queue.outstanding += 1;
  operationQueues.set(operationId, queue);

  await previous;
  try {
    return await action();
  } finally {
    release?.();
    queue.outstanding -= 1;
    if (
      operationQueues.get(operationId) === queue &&
      queue.tail === tail &&
      queue.outstanding === 0
    ) {
      operationQueues.delete(operationId);
    }
  }
}
