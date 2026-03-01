import React from "react";

interface MedicalSourceStats {
  local_hits: number;
  academic_hits: number;
  fallback_to_academic: boolean;
  collection?: string;
}

interface MedicalSourceStatsBarProps {
  stats: MedicalSourceStats;
}

export default function MedicalSourceStatsBar({ stats }: MedicalSourceStatsBarProps) {
  return (
    <div className="mt-4 rounded-lg border border-teal-700/40 bg-teal-950/30 p-3 text-sm text-teal-100">
      <div className="font-semibold mb-1">Medical Retrieval Stats</div>
      <div className="flex flex-wrap gap-4">
        <span>Local (Qdrant): {stats.local_hits ?? 0}</span>
        <span>Academic: {stats.academic_hits ?? 0}</span>
        <span>Fallback: {stats.fallback_to_academic ? "Yes" : "No"}</span>
        {stats.collection ? <span>Collection: {stats.collection}</span> : null}
      </div>
    </div>
  );
}
