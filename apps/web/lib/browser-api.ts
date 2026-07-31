"use client";

import type {
  ApiErrorPayload,
  BackendStatus,
  OnboardingInput,
  OnboardingResult,
  OwnerAuthStatus,
  WorkflowInput,
  WorkflowResult,
} from "./api-types";

export const OWNER_AUTH_REQUIRED_EVENT =
  "autonomerce:owner-auth-required";

export class BrowserApiError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "BrowserApiError";
  }
}

async function request<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(path, {
    ...init,
    cache: "no-store",
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  const payload = (await response.json()) as T | ApiErrorPayload;
  if (!response.ok) {
    const error =
      payload && typeof payload === "object" && "error" in payload
        ? payload.error
        : { code: "request_failed", message: "Request failed" };
    if (
      response.status === 401 &&
      path !== "/api/autonomerce/auth/login" &&
      typeof window !== "undefined"
    ) {
      window.dispatchEvent(new Event(OWNER_AUTH_REQUIRED_EVENT));
    }
    throw new BrowserApiError(error.message, error.code, response.status);
  }
  return payload as T;
}

export function getBackendStatus(): Promise<BackendStatus> {
  return request<BackendStatus>("/api/autonomerce/status");
}

export function getOwnerAuthStatus(): Promise<OwnerAuthStatus> {
  return request<OwnerAuthStatus>("/api/autonomerce/auth/status");
}

export function loginOwner(ownerToken: string): Promise<OwnerAuthStatus> {
  return request<OwnerAuthStatus>("/api/autonomerce/auth/login", {
    method: "POST",
    body: JSON.stringify({ ownerToken }),
  });
}

export function logoutOwner(): Promise<OwnerAuthStatus> {
  return request<OwnerAuthStatus>("/api/autonomerce/auth/logout", {
    method: "POST",
    body: "{}",
  });
}

export function activateSeller(
  input: OnboardingInput,
): Promise<OnboardingResult> {
  return request<OnboardingResult>("/api/autonomerce/onboarding", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function runWorkflow(
  input: WorkflowInput,
): Promise<WorkflowResult> {
  return request<WorkflowResult>("/api/autonomerce/workflow", {
    method: "POST",
    body: JSON.stringify(input),
  });
}
