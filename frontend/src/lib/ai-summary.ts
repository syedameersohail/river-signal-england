import type { SiteEntry } from "../types";

const DATA_VERSION = "v1";

export function buildSiteDataForAI(site: SiteEntry) {
  return {
    site_name: site.display_name || site.site_label,
    site_id: site.site_id,
    national_rank: site.anomaly_rank,
    severity: getSeverityLabel(site.anomaly_score),
    peer_group: site.wfd_type || site.score_reference || "Unknown",
    peer_group_size: site.score_peer_group_size || 0,
    wfd_status: site.wfd_status
      ? {
          ecological: site.wfd_status.ecological_status || "Not available",
          chemical: site.wfd_status.chemical_status || "Not available",
          overall: site.wfd_status.overall_status || "Not available",
        }
      : "Not available",
    flagged_determinands: (site.drivers || []).map((d) => ({
      name: d.name,
      direction: d.direction,
      description: d.description,
    })),
    cross_typology_match: site.peer_agreement_ratio != null
      ? `${Math.round(site.peer_agreement_ratio * 5)} out of 5`
      : "Not available",
    cso_discharges: site.incidents?.total_edm_spills || 0,
    cso_total_hours: site.incidents?.total_spill_hours || 0,
    regulated_discharge_points: site.discharge_points
      ? {
          sewage_works: site.discharge_points.sewage_works_count,
          storm_overflows: site.discharge_points.storm_overflows_count,
          industrial: site.discharge_points.industrial_discharges_count,
        }
      : { sewage_works: 0, storm_overflows: 0, industrial: 0 },
    nearest_facility: site.discharge_points?.nearest_sewage_work?.name
      || site.discharge_points?.nearest_industrial?.name
      || "Not available",
    waterbody: site.water_body_name || "Not available",
    region: site.region || "Not available",
    data_confidence: site.confidence_tier || "Not available",
  };
}

function getSeverityLabel(score: number): string {
  if (score >= 8) return "Extreme";
  if (score >= 4) return "High";
  if (score >= 1.65) return "Moderate";
  return "Lower";
}

function getCachedSummary(siteId: string): string | null {
  try {
    return localStorage.getItem(`rs-summary-${siteId}-${DATA_VERSION}`);
  } catch {
    return null;
  }
}

function cacheSummary(siteId: string, summary: string): void {
  try {
    localStorage.setItem(`rs-summary-${siteId}-${DATA_VERSION}`, summary);
  } catch {
    /* Fail silently if storage is full */
  }
}

export async function getSiteSummary(site: SiteEntry): Promise<string> {
  const cached = getCachedSummary(site.site_id);
  if (cached) return cached;

  try {
    const siteData = buildSiteDataForAI(site);
    const response = await fetch("/api/generate-summary", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(siteData),
    });

    const data = await response.json();
    if (!data.summary) throw new Error("No summary returned");

    cacheSummary(site.site_id, data.summary);
    return data.summary;
  } catch (error) {
    console.error("Failed to generate summary:", error);
    return "Summary unavailable. See the data below for details.";
  }
}
