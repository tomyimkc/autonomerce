import assert from "node:assert/strict";
import {
  chmod,
  mkdtemp,
  readFile,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { delimiter, dirname, join } from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";

const DEPLOY_SCRIPT = fileURLToPath(
  new URL("../../../infra/deploy_cloud_run_web.sh", import.meta.url),
);
const DOCKERFILE = fileURLToPath(
  new URL("../../../infra/Dockerfile.web", import.meta.url),
);
const IMAGE =
  "us-central1-docker.pkg.dev/example/autonomerce/web@sha256:" +
  "a".repeat(64);

interface DeploymentResult {
  status: number | null;
  stdout: string;
  stderr: string;
  args: string[];
}

async function runDeployment(
  overrides: Record<string, string | undefined>,
): Promise<DeploymentResult> {
  const directory = await mkdtemp(join(tmpdir(), "autonomerce-web-deploy-"));
  const gcloud = join(directory, "gcloud");
  const log = join(directory, "gcloud.args");
  await writeFile(
    gcloud,
    `#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$@" > "$GCLOUD_ARGS_LOG"
`,
    "utf8",
  );
  await chmod(gcloud, 0o755);

  const baseEnvironment: NodeJS.ProcessEnv = {
    PATH: `${directory}${delimiter}${process.env.PATH ?? "/usr/bin:/bin"}`,
    HOME: process.env.HOME ?? directory,
    NODE_ENV: "test",
    GCLOUD_ARGS_LOG: log,
    GOOGLE_CLOUD_PROJECT: "example-project",
    GOOGLE_CLOUD_REGION: "us-central1",
    AUTONOMERCE_WEB_IMAGE: IMAGE,
    AUTONOMERCE_WEB_RUNTIME_SERVICE_ACCOUNT:
      "autonomerce-web@example-project.iam.gserviceaccount.com",
    AUTONOMERCE_WEB_PUBLIC_ORIGIN: "https://web.example",
    AUTONOMERCE_WEB_MODE: "DEMO",
    AUTONOMERCE_API_IAM_AUTH: "false",
  };
  for (const [name, value] of Object.entries(overrides)) {
    if (value === undefined) {
      delete baseEnvironment[name];
    } else {
      baseEnvironment[name] = value;
    }
  }

  const result = spawnSync("bash", [DEPLOY_SCRIPT], {
    cwd: dirname(DEPLOY_SCRIPT),
    env: baseEnvironment,
    encoding: "utf8",
  });

  let args: string[] = [];
  try {
    args = (await readFile(log, "utf8"))
      .split("\n")
      .filter(Boolean);
  } catch {
    // Validation failures intentionally exit before invoking the fake gcloud.
  }
  await rm(directory, { recursive: true, force: true });
  return {
    status: result.status,
    stdout: result.stdout,
    stderr: result.stderr,
    args,
  };
}

function argumentValue(args: string[], flag: string): string {
  const index = args.indexOf(flag);
  assert.notEqual(index, -1, `missing ${flag}`);
  assert.ok(args[index + 1], `missing value after ${flag}`);
  return args[index + 1];
}

test("web image is digest-pinned, reproducible, standalone, and non-root", async () => {
  const dockerfile = await readFile(DOCKERFILE, "utf8");

  assert.match(
    dockerfile,
    /^FROM node:[^\s@]+@sha256:[a-f0-9]{64} AS base$/m,
  );
  assert.match(dockerfile, /npm ci --no-audit --no-fund/);
  assert.match(dockerfile, /\.next\/standalone/);
  assert.match(dockerfile, /\.next\/static/);
  assert.match(dockerfile, /^USER node$/m);
  assert.match(dockerfile, /HOSTNAME=0\.0\.0\.0/);
  assert.match(dockerfile, /CMD \["node", "server\.js"\]/);
  assert.doesNotMatch(
    dockerfile,
    /(?:ARG|ENV)\s+NEXT_PUBLIC_\S*(?:BEARER|OWNER_TOKEN|SESSION_SECRET)/,
  );
});

test("DEMO deploy is explicit, synthetic, public, and clears backend secrets", async () => {
  const result = await runDeployment({
    AUTONOMERCE_WEB_MODE: "DEMO",
  });

  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(result.args.slice(0, 3), [
    "run",
    "deploy",
    "autonomerce-web",
  ]);
  assert.ok(result.args.includes("--allow-unauthenticated"));
  assert.ok(result.args.includes("--invoker-iam-check"));
  assert.ok(result.args.includes("--clear-secrets"));
  assert.equal(
    argumentValue(result.args, "--labels"),
    [
      "autonomerce-exposure=public",
      "autonomerce-web-mode=demo",
      "autonomerce-mode=demo",
      "autonomerce-payment=offline",
    ].join(","),
  );
  const env = argumentValue(result.args, "--set-env-vars");
  assert.match(env, /AUTONOMERCE_WEB_MODE=DEMO/);
  assert.match(env, /AUTONOMERCE_DEMO_SYNTHETIC_ONLY=true/);
  assert.match(env, /AUTONOMERCE_ALLOW_MOVES_FUNDS=false/);
  assert.match(env, /AUTONOMERCE_API_IAM_AUTH=false/);
  assert.match(env, /AUTONOMERCE_WEB_TRUST_PROXY_HEADERS=false/);
  assert.doesNotMatch(
    env,
    /AUTONOMERCE_API_(?:BASE_URL|PRIVATE_ORIGIN|IAM_AUDIENCE|BEARER)/,
  );
  assert.doesNotMatch(env, /AUTONOMERCE_WEB_(?:OWNER_TOKEN|SESSION_SECRET)/);
});

test("LIVE deploy enables IAM with a pinned private-origin audience and one instance", async () => {
  const result = await runDeployment({
    AUTONOMERCE_WEB_MODE: "LIVE",
    AUTONOMERCE_API_PRIVATE_ORIGIN: "https://private-api.example",
    AUTONOMERCE_API_IAM_AUTH: "true",
    AUTONOMERCE_API_IAM_AUDIENCE: "https://private-api.example/",
    AUTONOMERCE_API_BEARER_TOKEN_SECRET_REF: "api-bearer:7",
    AUTONOMERCE_WEB_OWNER_TOKEN_SECRET_REF: "web-owner:4",
    AUTONOMERCE_WEB_SESSION_SECRET_REF: "web-session:9",
  });

  assert.equal(result.status, 0, result.stderr);
  assert.equal(argumentValue(result.args, "--max"), "1");
  assert.equal(argumentValue(result.args, "--max-instances"), "1");
  assert.equal(argumentValue(result.args, "--concurrency"), "1");
  assert.equal(
    argumentValue(result.args, "--labels"),
    [
      "autonomerce-exposure=public",
      "autonomerce-web-mode=live",
      "autonomerce-mode=live-bff",
      "autonomerce-payment=offline",
    ].join(","),
  );
  const env = argumentValue(result.args, "--set-env-vars");
  assert.match(env, /AUTONOMERCE_WEB_MODE=LIVE/);
  assert.match(
    env,
    /AUTONOMERCE_API_PRIVATE_ORIGIN=https:\/\/private-api\.example/,
  );
  assert.match(env, /AUTONOMERCE_API_IAM_AUTH=true/);
  assert.match(
    env,
    /AUTONOMERCE_API_IAM_AUDIENCE=https:\/\/private-api\.example/,
  );
  assert.match(env, /AUTONOMERCE_ALLOW_MOVES_FUNDS=false/);
  assert.doesNotMatch(
    env,
    /AUTONOMERCE_(?:API_BEARER_TOKEN|WEB_OWNER_TOKEN|WEB_SESSION_SECRET)=/,
  );
  assert.equal(
    argumentValue(result.args, "--set-secrets"),
    [
      "AUTONOMERCE_API_BEARER_TOKEN=api-bearer:7",
      "AUTONOMERCE_WEB_OWNER_TOKEN=web-owner:4",
      "AUTONOMERCE_WEB_SESSION_SECRET=web-session:9",
    ].join(","),
  );
});

test("funds movement remains locked unless LIVE explicitly opts in", async () => {
  const demo = await runDeployment({
    AUTONOMERCE_WEB_MODE: "DEMO",
    AUTONOMERCE_ALLOW_MOVES_FUNDS: "true",
  });
  assert.equal(demo.status, 2);
  assert.match(demo.stderr, /DEMO mode cannot enable funds movement/);

  const live = await runDeployment({
    AUTONOMERCE_WEB_MODE: "LIVE_BFF",
    AUTONOMERCE_API_PRIVATE_ORIGIN: "https://private-api.example",
    AUTONOMERCE_API_BEARER_TOKEN_SECRET_REF: "api-bearer:7",
    AUTONOMERCE_WEB_OWNER_TOKEN_SECRET_REF: "web-owner:4",
    AUTONOMERCE_WEB_SESSION_SECRET_REF: "web-session:9",
    AUTONOMERCE_ALLOW_MOVES_FUNDS: "true",
  });
  assert.equal(live.status, 0, live.stderr);
  const liveEnv = argumentValue(live.args, "--set-env-vars");
  assert.match(liveEnv, /AUTONOMERCE_ALLOW_MOVES_FUNDS=true/);
  assert.match(liveEnv, /AUTONOMERCE_API_IAM_AUTH=false/);
  assert.doesNotMatch(liveEnv, /AUTONOMERCE_API_IAM_AUDIENCE/);
});

test("deployment rejects mutable images, non-HTTPS origins, and implicit mode", async () => {
  const mutableImage = await runDeployment({
    AUTONOMERCE_WEB_IMAGE:
      "us-central1-docker.pkg.dev/example/autonomerce/web:latest",
  });
  assert.equal(mutableImage.status, 2);
  assert.match(mutableImage.stderr, /immutable image digest/);

  const insecureOrigin = await runDeployment({
    AUTONOMERCE_WEB_PUBLIC_ORIGIN: "http://web.example",
  });
  assert.equal(insecureOrigin.status, 2);
  assert.match(insecureOrigin.stderr, /HTTPS origin/);

  const implicitMode = await runDeployment({
    AUTONOMERCE_WEB_MODE: undefined,
  });
  assert.equal(implicitMode.status, 2);
  assert.match(implicitMode.stderr, /AUTONOMERCE_WEB_MODE must be set/);
});

test("DEMO rejects backend configuration and LIVE requires three different pinned secrets", async () => {
  const demoWithBackend = await runDeployment({
    AUTONOMERCE_API_PRIVATE_ORIGIN: "https://private-api.example",
  });
  assert.equal(demoWithBackend.status, 2);
  assert.match(demoWithBackend.stderr, /synthetic\/no-backend/);

  const missingLiveSecret = await runDeployment({
    AUTONOMERCE_WEB_MODE: "LIVE",
    AUTONOMERCE_API_PRIVATE_ORIGIN: "https://private-api.example",
    AUTONOMERCE_API_BEARER_TOKEN_SECRET_REF: "api-bearer:7",
    AUTONOMERCE_WEB_OWNER_TOKEN_SECRET_REF: "web-owner:4",
  });
  assert.equal(missingLiveSecret.status, 2);
  assert.match(
    missingLiveSecret.stderr,
    /AUTONOMERCE_WEB_SESSION_SECRET_REF/,
  );

  const reusedLiveSecret = await runDeployment({
    AUTONOMERCE_WEB_MODE: "LIVE",
    AUTONOMERCE_API_PRIVATE_ORIGIN: "https://private-api.example",
    AUTONOMERCE_API_BEARER_TOKEN_SECRET_REF: "shared-secret:7",
    AUTONOMERCE_WEB_OWNER_TOKEN_SECRET_REF: "shared-secret:8",
    AUTONOMERCE_WEB_SESSION_SECRET_REF: "web-session:9",
  });
  assert.equal(reusedLiveSecret.status, 2);
  assert.match(reusedLiveSecret.stderr, /three distinct secrets/);

  const floatingSecretVersion = await runDeployment({
    AUTONOMERCE_WEB_MODE: "LIVE",
    AUTONOMERCE_API_PRIVATE_ORIGIN: "https://private-api.example",
    AUTONOMERCE_API_BEARER_TOKEN_SECRET_REF: "api-bearer:latest",
    AUTONOMERCE_WEB_OWNER_TOKEN_SECRET_REF: "web-owner:4",
    AUTONOMERCE_WEB_SESSION_SECRET_REF: "web-session:9",
  });
  assert.equal(floatingSecretVersion.status, 2);
  assert.match(floatingSecretVersion.stderr, /explicit numeric secret version/);
});

test("deployment validates IAM auth mode and audience fail closed", async () => {
  const missingIamMode = await runDeployment({
    AUTONOMERCE_WEB_MODE: "LIVE",
    AUTONOMERCE_API_IAM_AUTH: undefined,
    AUTONOMERCE_API_PRIVATE_ORIGIN: "https://private-api.example",
  });
  assert.equal(missingIamMode.status, 2);
  assert.match(
    missingIamMode.stderr,
    /AUTONOMERCE_API_IAM_AUTH must be set/,
  );

  const invalidIamMode = await runDeployment({
    AUTONOMERCE_WEB_MODE: "LIVE",
    AUTONOMERCE_API_IAM_AUTH: "automatic",
    AUTONOMERCE_API_PRIVATE_ORIGIN: "https://private-api.example",
  });
  assert.equal(invalidIamMode.status, 2);
  assert.match(
    invalidIamMode.stderr,
    /AUTONOMERCE_API_IAM_AUTH must be exactly true or false/,
  );

  const missingAudience = await runDeployment({
    AUTONOMERCE_WEB_MODE: "LIVE",
    AUTONOMERCE_API_IAM_AUTH: "true",
    AUTONOMERCE_API_PRIVATE_ORIGIN: "https://private-api.example",
  });
  assert.equal(missingAudience.status, 2);
  assert.match(
    missingAudience.stderr,
    /requires AUTONOMERCE_API_IAM_AUDIENCE/,
  );

  const mismatchedAudience = await runDeployment({
    AUTONOMERCE_WEB_MODE: "LIVE",
    AUTONOMERCE_API_IAM_AUTH: "true",
    AUTONOMERCE_API_IAM_AUDIENCE: "https://other-api.example",
    AUTONOMERCE_API_PRIVATE_ORIGIN: "https://private-api.example",
  });
  assert.equal(mismatchedAudience.status, 2);
  assert.match(
    mismatchedAudience.stderr,
    /must match AUTONOMERCE_API_PRIVATE_ORIGIN/,
  );

  const disabledWithAudience = await runDeployment({
    AUTONOMERCE_WEB_MODE: "LIVE",
    AUTONOMERCE_API_IAM_AUTH: "false",
    AUTONOMERCE_API_IAM_AUDIENCE: "https://private-api.example",
    AUTONOMERCE_API_PRIVATE_ORIGIN: "https://private-api.example",
  });
  assert.equal(disabledWithAudience.status, 2);
  assert.match(
    disabledWithAudience.stderr,
    /must be unset when IAM auth is disabled/,
  );

  const demoWithIam = await runDeployment({
    AUTONOMERCE_WEB_MODE: "DEMO",
    AUTONOMERCE_API_IAM_AUTH: "true",
    AUTONOMERCE_API_IAM_AUDIENCE: "https://private-api.example",
  });
  assert.equal(demoWithIam.status, 2);
  assert.match(
    demoWithIam.stderr,
    /DEMO mode requires AUTONOMERCE_API_IAM_AUTH=false/,
  );
});

test("deployment refuses direct or NEXT_PUBLIC client credentials", async () => {
  const directSecret = await runDeployment({
    AUTONOMERCE_API_BEARER_TOKEN: "must-not-travel-on-the-command-line",
  });
  assert.equal(directSecret.status, 2);
  assert.match(directSecret.stderr, /must not be passed directly/);

  const directIamToken = await runDeployment({
    AUTONOMERCE_API_IAM_ID_TOKEN:
      "must-be-acquired-from-the-metadata-server",
  });
  assert.equal(directIamToken.status, 2);
  assert.match(directIamToken.stderr, /must not be passed directly/);

  const clientSecret = await runDeployment({
    NEXT_PUBLIC_AUTONOMERCE_WEB_OWNER_TOKEN:
      "must-never-be-bundled-into-browser-code",
  });
  assert.equal(clientSecret.status, 2);
  assert.match(clientSecret.stderr, /expose a server-only credential/);

  const clientIamToken = await runDeployment({
    NEXT_PUBLIC_AUTONOMERCE_API_ID_TOKEN:
      "must-never-be-bundled-into-browser-code",
  });
  assert.equal(clientIamToken.status, 2);
  assert.match(clientIamToken.stderr, /expose a server-only credential/);
});
