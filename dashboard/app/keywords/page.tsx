"use client";
import EntityPage from "@/components/EntityPage";

export default function Page() {
  return (
    <EntityPage
      config={{
        endpoint: "keywords",
        title: "Keyword Dashboard",
        subtitle: "The search terms shoppers use, and what each one returns.",
        labelKey: "keyword",
        labelHeader: "Keyword",
        note: "This is a partial breakdown. Keyword reports cover only the spend attributed to a specific search term, so the totals here are less than each platform's billed total — see the Executive page for the full spend and revenue.",
        extraColumns: [{ key: "match_type", label: "Match Type" }],
      }}
    />
  );
}
