import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "WalkIn Jobs India — Find Walk-in Interviews Today",
  description:
    "Discover the latest walk-in job opportunities across India from Naukri, LinkedIn, and Indeed. Filter by city, salary, experience. Updated every 4 hours.",
  keywords: "walk-in jobs, walkin interview, fresher jobs india, direct interview, job openings today",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={inter.className}>{children}</body>
    </html>
  );
}
