"use client";

import { useState } from "react";

import { Icon } from "./icons";

export function CopyButton({
  value,
  label = "Copy",
  compact = false,
}: {
  value: string;
  label?: string;
  compact?: boolean;
}) {
  const [copied, setCopied] = useState(false);

  async function copyValue() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  }

  return (
    <button
      className={`copyButton ${compact ? "copyButtonCompact" : ""}`}
      type="button"
      onClick={copyValue}
      aria-label={`${label}: ${value}`}
    >
      <Icon name={copied ? "check" : "copy"} width={15} height={15} />
      <span>{copied ? "Copied" : label}</span>
    </button>
  );
}
