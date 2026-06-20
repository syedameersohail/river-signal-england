import type { SeverityBand, SiteEntry } from "../types";

export type ConfidenceBand = "Strong" | "Moderate" | "Limited" | "Unknown";
export type EvidenceBand = "strong" | "good" | "moderate" | "thin";

const NATIONAL_OBSERVATION_MEDIAN = 411;

export const WFD_EXPLAINERS: Record<string, string> = {
  Low: "lowland altitude",
  Mid: "mid-altitude",
  High: "upland altitude",
  Small: "small river size",
  Medium: "medium river size",
  Large: "large river size",
  "Extra Small": "very small river size",
  Calcareous: "chalk or limestone geology",
  Siliceous: "sandstone or granite geology",
  Organic: "peat or organic soil geology",
  Salt: "salt-influenced geology",
};

export function explainWfdType(wfdType: string | null | undefined): string[] {
  if (!wfdType) {
    return [];
  }

  return wfdType
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => WFD_EXPLAINERS[part] ?? part.toLowerCase());
}

export function peerContextSentence(site: SiteEntry): string {
  const reference = (site.score_reference || "").toLowerCase();
  if (reference.includes("geographic") || reference.includes("global")) {
    return "Compared against the 20 geographically nearest monitoring sites, because this river type has too few sites nationally for reliable group comparison.";
  }

  const wfdType = site.wfd_type_resolved || site.wfd_type || site.score_reference;
  const count = site.score_peer_group_size?.toLocaleString("en-GB") ?? "similar";
  const expanded = explainWfdType(wfdType);
  if (wfdType && expanded.length > 0) {
    return `Compared against ${count} sites with the same natural characteristics: ${expanded.join(", ")} (WFD type: ${wfdType}).`;
  }

  return `Compared against ${count} similar monitoring sites.`;
}

export function severityDescription(severity: SeverityBand): string {
  // Approximate score bands for the current feed; keep in sync with backend percentile config.
  const descriptions: Record<SeverityBand, string> = {
    Extreme: "Chemistry is highly unusual compared with similar rivers. In the top 1% nationally.",
    High: "Chemistry is notably unusual. In the top 5% nationally.",
    Moderate: "Chemistry shows some differences from similar rivers, but within a wider range.",
    Lower: "Chemistry is broadly consistent with similar rivers.",
  };

  return descriptions[severity];
}

export function severityShortDescription(severity: SeverityBand): string {
  const descriptions: Record<SeverityBand, string> = {
    Extreme: "Very few similar rivers look like this",
    High: "Most similar rivers do not look like this",
    Moderate: "Some differences from similar rivers",
    Lower: "Broadly consistent with similar rivers",
  };

  return descriptions[severity];
}

export function severityPercentileNote(severity: SeverityBand): string | null {
  const notes: Partial<Record<SeverityBand, string>> = {
    Extreme: "(top 1% nationally)",
    High: "(top 5% nationally)",
  };

  return notes[severity] ?? null;
}

export function describePeerAgreement(ratio: number | null | undefined, k = 5): string {
  if (ratio == null || Number.isNaN(ratio)) {
    return "Chemical neighbourhood not available";
  }

  const matching = Math.round(ratio * k);
  if (matching === 0) {
    return "None of its chemical neighbours are the same river type";
  }
  if (matching === k) {
    return "All chemical neighbours are the same river type";
  }
  if (matching === 1) {
    return `Only 1 in ${k} chemical neighbours are the same river type`;
  }
  return `${matching} in ${k} chemical neighbours are the same river type`;
}

export function confidenceMeta(site: SiteEntry): {
  chemicalMeasurements: string;
  dateRange: string;
  evidence: {
    band: EvidenceBand;
    fillPercent: number;
    label: string;
  };
  frequencyLabel: string | null;
  monthYearRange: string;
  readings: string;
  roughFrequency: string | null;
  samplingDates: string;
  samplingVisits: string;
  visits: string;
} {
  const firstMonthYear = formatMonthYear(site.first_sample);
  const lastMonthYear = formatMonthYear(site.last_sample);
  const firstDate = formatDate(site.first_sample);
  const lastDate = formatDate(site.last_sample);
  const observations = site.total_observations?.toLocaleString("en-GB") ?? "unknown";
  const visits = site.distinct_sample_dates?.toLocaleString("en-GB") ?? "unknown";
  const monthYearRange =
    firstMonthYear && lastMonthYear ? `${firstMonthYear} to ${lastMonthYear}` : "date range unknown";
  const dateRange = firstDate && lastDate ? `${firstDate} to ${lastDate}` : "date range unknown";

  return {
    chemicalMeasurements:
      typeof site.total_observations === "number"
        ? `${observations} chemical measurements`
        : `${observations} chemical measurements`,
    dateRange,
    evidence: evidenceBase(site.total_observations),
    frequencyLabel: frequencyLabel(site.avg_days_between_visits),
    monthYearRange,
    readings: typeof site.total_observations === "number" ? `${observations} readings` : observations,
    roughFrequency: roughFrequencyLabel(site.avg_days_between_visits),
    samplingDates:
      typeof site.distinct_sample_dates === "number"
        ? `${visits} sampling dates`
        : `${visits} sampling dates`,
    samplingVisits:
      typeof site.distinct_sample_dates === "number"
        ? `${visits} sampling visits`
        : `${visits} sampling visits`,
    visits: typeof site.distinct_sample_dates === "number" ? `${visits} visits` : `${visits} visits`,
  };
}

export function siteConfidence(site: SiteEntry): {
  band: ConfidenceBand;
  dotClass: string;
  label: string;
} {
  if (site.confidence_tier === "well") {
    return {
      band: "Strong",
      dotClass: "bg-emerald-600",
      label: "Well-monitored",
    };
  }

  if (site.confidence_tier === "moderate") {
    return {
      band: "Moderate",
      dotClass: "bg-amber-500",
      label: "Moderately monitored",
    };
  }

  return {
    band: site.confidence_tier ? "Limited" : "Unknown",
    dotClass: "bg-slate-400",
    label: site.confidence_tier ? "Limited data" : "Data coverage unavailable",
  };
}

export function confidenceFillClass(site: SiteEntry): string {
  if (site.confidence_tier === "well") {
    return "bg-emerald-600";
  }
  if (site.confidence_tier === "moderate") {
    return "bg-amber-500";
  }
  return "bg-slate-400";
}

export function confidenceFrequencyText(site: SiteEntry): string {
  const roughFrequency = roughFrequencyLabel(site.avg_days_between_visits);
  if (site.confidence_tier === "limited") {
    return "No recent data";
  }
  return roughFrequency ? `Roughly ${roughFrequency}` : "Sampling frequency unavailable";
}

export function frequencyLabel(avgDays: number | null | undefined): string | null {
  if (avgDays == null || Number.isNaN(avgDays)) {
    return null;
  }
  if (avgDays <= 14) {
    return "fortnightly sampling";
  }
  if (avgDays <= 45) {
    return "monthly sampling";
  }
  if (avgDays <= 120) {
    return "quarterly sampling";
  }
  if (avgDays <= 270) {
    return "twice-yearly sampling";
  }
  if (avgDays <= 450) {
    return "annual sampling";
  }
  return "infrequent sampling";
}

function roughFrequencyLabel(avgDays: number | null | undefined): string | null {
  return frequencyLabel(avgDays)?.replace(/ sampling$/, "") ?? null;
}

function evidenceBase(observations: number | null | undefined): {
  band: EvidenceBand;
  fillPercent: number;
  label: string;
} {
  const count = typeof observations === "number" ? observations : 0;
  const fillPercent = Math.min(100, (count / NATIONAL_OBSERVATION_MEDIAN) * 50);

  if (count >= 800) {
    return { band: "strong", fillPercent, label: "Strong evidence base" };
  }
  if (count >= 400) {
    return { band: "good", fillPercent, label: "Good evidence base" };
  }
  if (count >= 200) {
    return { band: "moderate", fillPercent, label: "Moderate evidence base" };
  }
  return { band: "thin", fillPercent, label: "Thin evidence base" };
}

function formatMonthYear(value: string | null | undefined): string | null {
  return formatDatePart(value, {
    month: "short",
    year: "numeric",
  });
}

function formatDate(value: string | null | undefined): string | null {
  return formatDatePart(value, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function formatDatePart(
  value: string | null | undefined,
  options: Intl.DateTimeFormatOptions,
): string | null {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return new Intl.DateTimeFormat("en-GB", {
    ...options,
    timeZone: "Europe/London",
  }).format(date);
}
