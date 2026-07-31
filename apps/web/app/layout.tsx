import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./globals.css";

export const metadata: Metadata = {
  title: "Autonomerce — Give your agent a sales department",
  description:
    "An owner console with explicit static DEMO mode and a server-proxied LIVE mode for autonomous offers, Circle USDC settlement, fulfillment, and agent revenue.",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
