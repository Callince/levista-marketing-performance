"use client";
import EntityPage from "@/components/EntityPage";

export default function Page() {
  return (
    <EntityPage
      config={{
        endpoint: "campaigns",
        title: "Campaign Dashboard",
        subtitle: "Every campaign across every platform, ranked by what it earned.",
        labelKey: "campaign_name",
        labelHeader: "Campaign",
      }}
    />
  );
}
