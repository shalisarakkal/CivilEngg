import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Civil Engineering AI",
  description: "Local-first civil engineering document and measurement workspace",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
