import type { ReactNode } from "react";
import { Inter } from "next/font/google";
import { ToastProvider } from "./components/Toast";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter",
});

export const metadata = {
  title: "Work Intelligence Platform",
  description: "Turn Telegram work discussions into reviewed Work Items.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={inter.variable}>
      <body><ToastProvider>{children}</ToastProvider></body>
    </html>
  );
}
