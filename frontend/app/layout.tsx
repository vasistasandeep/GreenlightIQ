import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CineROI AI",
  description:
    "OTT content acquisition, licensing, greenlighting & historical backtesting intelligence engine",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
