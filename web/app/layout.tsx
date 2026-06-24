import type { ReactNode } from "react";
import "./globals.css";

export const metadata = {
  title: "Work Intelligence Platform",
  description: "Turn Telegram work discussions into reviewed Work Items.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
