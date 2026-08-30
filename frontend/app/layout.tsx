import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Gold Research Agent",
  description: "XAU/USD multi-agent research system",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="bg-[#212121]">
      <body>{children}</body>
    </html>
  );
}
