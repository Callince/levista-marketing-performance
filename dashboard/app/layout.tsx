import type { Metadata } from "next";
import { Geist } from "next/font/google";
import "./globals.css";
import { Shell } from "@/components/ui";

const geist = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Levista Marketing Performance",
  description: "Advertising performance across Amazon, Flipkart, Instamart, Zepto, BigBasket and Blinkit.",
};

// LayoutProps is a Next 16 global helper — no import needed.
export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geist.variable} h-full antialiased`}>
      <body className="min-h-full">
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
