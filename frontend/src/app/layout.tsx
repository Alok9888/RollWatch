import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "RollWatch — Deployment-Aware Health, Drift & Auto-Rollback Monitor",
  description:
    "Production SRE monitor for external endpoints and managed deployments with live TLS/latency telemetry, version drift detection, and automated rollbacks.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-[#090b10] text-slate-100 antialiased selection:bg-sky-500/30 selection:text-sky-100">
        {children}
      </body>
    </html>
  );
}
