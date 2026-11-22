import type { Metadata } from "next";
import { WorksCatalogApp } from "../../components/WorksCatalogApp";

export const metadata: Metadata = {
  title: "収録作品一覧 | 青空文庫 短単位コーパス検索",
  description:
    "青空文庫パブリックドメイン収録作品（17,343作品）の書誌一覧・作品名・著者名検索ページ",
};

export default function WorksPage() {
  return <WorksCatalogApp />;
}
