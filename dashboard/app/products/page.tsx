"use client";
import EntityPage from "@/components/EntityPage";
import { num } from "@/lib/api";

export default function Page() {
  return (
    <EntityPage
      config={{
        endpoint: "products",
        title: "Product Dashboard",
        subtitle: "Which advertised products actually sell, and which only cost money.",
        labelKey: "product_name",
        labelHeader: "Product",
        note: "This is a partial breakdown. Product reports cover only the spend attributed to a specific product, so the totals here are less than each platform's billed total — see the Executive page for the full spend and revenue.",
        extraColumns: [{ key: "atc", label: "Add to Cart", align: "right", format: (v) => num(v) }],
      }}
    />
  );
}
