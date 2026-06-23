import type { ReactNode } from "react";

export const metadata = {
  title: "AI Work Intelligence Platform",
  description: "Turn Telegram work discussions into reviewed Work Items.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body style={{ fontFamily: "system-ui, sans-serif", margin: 0 }}>{children}</body>
    </html>
  );
}
