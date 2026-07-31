const USDC_PATTERN = /^(0|[1-9]\d*)(?:\.(\d{1,6}))?$/;
const USDC_SCALE = 1_000_000n;

export function usdcToMicros(value: string): bigint {
  const match = USDC_PATTERN.exec(value);

  if (!match) {
    throw new Error(`Invalid canonical USDC value: ${value}`);
  }

  const [wholeText, fractionText = ""] = value.split(".");
  const paddedFraction = fractionText.padEnd(6, "0");

  return BigInt(wholeText) * USDC_SCALE + BigInt(paddedFraction || "0");
}

export function microsToUsdc(
  value: bigint,
  minimumFractionDigits = 0,
): string {
  if (value < 0n) {
    throw new Error("USDC value cannot be negative");
  }

  if (
    !Number.isInteger(minimumFractionDigits) ||
    minimumFractionDigits < 0 ||
    minimumFractionDigits > 6
  ) {
    throw new Error("minimumFractionDigits must be between zero and six");
  }

  const whole = value / USDC_SCALE;
  const fraction = (value % USDC_SCALE).toString().padStart(6, "0");
  let visibleFraction = fraction.replace(/0+$/, "");

  if (visibleFraction.length < minimumFractionDigits) {
    visibleFraction = fraction.slice(0, minimumFractionDigits);
  }

  return visibleFraction ? `${whole}.${visibleFraction}` : whole.toString();
}

export function formatUsdc(value: string, minimumFractionDigits = 2): string {
  return microsToUsdc(usdcToMicros(value), minimumFractionDigits);
}

export function sumUsdc(values: readonly string[]): string {
  const total = values.reduce(
    (sum, value) => sum + usdcToMicros(value),
    0n,
  );

  return microsToUsdc(total);
}

export function averageUsdc(values: readonly string[]): string {
  if (values.length === 0) {
    return "0";
  }

  const total = values.reduce(
    (sum, value) => sum + usdcToMicros(value),
    0n,
  );

  return microsToUsdc(total / BigInt(values.length));
}
