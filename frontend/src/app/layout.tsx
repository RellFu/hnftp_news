import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Hainan Free Trade Port News Pitch Assistant",
  description: "Retrieval Augmented News Pitch Assistant for Hainan Free Trade Port Policy Reporting",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en-GB">
      <body>{children}</body>
    </html>
  );
}
