"use client";

import { useState } from "react";
import { ActiveMode, PassiveMode } from "@/components";

const tabStyle = (active: boolean) => ({
  padding: "0.5rem 1rem",
  marginRight: "0.5rem",
  border: "none",
  background: active ? "#2563eb" : "transparent",
  color: active ? "#fff" : "#374151",
  cursor: "pointer",
  fontWeight: 500,
  borderBottom: active ? "2px solid #2563eb" : "2px solid transparent",
  marginBottom: "-1px",
});

export default function Home() {
  const [mainMode, setMainMode] = useState<"passive" | "active">("passive");

  return (
    <main style={{ maxWidth: 900, margin: "0 auto", padding: "2rem 1.5rem" }}>
      <h1 style={{ marginBottom: "0.5rem", fontSize: "1.5rem" }}>
        Hainan Free Trade Port News Pitch Assistant
      </h1>
      <p style={{ marginBottom: "1.5rem", color: "#6b7280", fontSize: "0.9375rem" }}>
        Retrieval Augmented News Pitch Assistant for Policy Reporting
      </p>

      <nav style={{ marginBottom: "1rem", display: "flex", gap: "1rem", flexWrap: "wrap" }}>
        <a href="/" style={{ color: "#374151", textDecoration: "none" }}>Pitch</a>
        <a href="/corpus" style={{ color: "#374151", textDecoration: "none" }}>Corpus</a>
        <a href="/audit" style={{ color: "#374151", textDecoration: "none" }}>Audit Log</a>
      </nav>

      <div style={{ marginBottom: "1.5rem", borderBottom: "1px solid #e5e7eb" }}>
        <button type="button" onClick={() => setMainMode("passive")} style={tabStyle(mainMode === "passive")}>
          Passive retrieval
        </button>
        <button type="button" onClick={() => setMainMode("active")} style={tabStyle(mainMode === "active")}>
          Active retrieval
        </button>
      </div>

      {mainMode === "passive" && <PassiveMode />}
      {mainMode === "active" && <ActiveMode />}
    </main>
  );
}
