import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "青空文庫 短単位コーパス検索",
  description:
    "青空文庫パブリックドメイン全作品を対象にした短単位・共起 KWIC コーパス検索アプリ",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ja" className="h-full antialiased">
      <body className="min-h-full bg-[#f7f8fa] text-slate-900">{children}</body>
    </html>
  );
}
