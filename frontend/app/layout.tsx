import type { Metadata } from "next";
import "./globals.css";
import { ChatWidget } from "./_components/chat-widget";

export const metadata: Metadata = {
  title: {
    default: "CineROI AI",
    template: "%s - CineROI AI",
  },
  description:
    "OTT content acquisition, licensing, greenlighting & historical backtesting intelligence engine",
  icons: { icon: "/icon.svg" },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-slate-950 text-slate-100 antialiased">
        {children}
        <ChatWidget />
      </body>
    </html>
  );
}