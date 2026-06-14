import type { Filters, RankedFeed, SeverityBand, SiteEntry } from "../types";

export const productNames = ["River Signal"];

export async function loadRankedFeed(): Promise<RankedFeed> {
  const response = await fetch("/data/ranked_feed.json");

  if (!response.ok) {
    throw new Error("The ranked river chemistry feed could not be loaded.");
  }

  return response.json();
}

export function titleCaseSiteName(value: string | undefined): string {
  if (!value) {
    return "Unnamed monitoring site";
  }

  const smallWords = new Set(["and", "as", "at", "by", "for", "in", "of", "on", "the", "to"]);

  return value
    .toLowerCase()
    .split(/(\s+|-|\/)/)
    .map((part, index) => {
      if (!/[a-z]/.test(part)) {
        return part;
      }

      if (index > 0 && smallWords.has(part)) {
        return part;
      }

      return part.charAt(0).toUpperCase() + part.slice(1);
    })
    .join("");
}

export function getSeverity(score: number): SeverityBand {
  if (score >= 8) {
    return "Extreme";
  }

  if (score >= 4) {
    return "High";
  }

  if (score >= 1.65) {
    return "Moderate";
  }

  return "Lower";
}

export function getSeverityClasses(severity: SeverityBand): string {
  const classes: Record<SeverityBand, string> = {
    Extreme: "border-red-800 bg-red-800 text-white",
    High: "border-red-700 bg-red-100 text-red-900",
    Moderate: "border-amber-600 bg-amber-100 text-amber-950",
    Lower: "border-emerald-700 bg-emerald-100 text-emerald-950",
  };

  return classes[severity];
}

export function getSeverityDot(severity: SeverityBand): string {
  const classes: Record<SeverityBand, string> = {
    Extreme: "bg-red-800",
    High: "bg-red-600",
    Moderate: "bg-amber-500",
    Lower: "bg-emerald-600",
  };

  return classes[severity];
}

export function getSeverityHex(severity: SeverityBand): string {
  const colours: Record<SeverityBand, string> = {
    Extreme: "#991b1b",
    High: "#dc2626",
    Moderate: "#d97706",
    Lower: "#15803d",
  };

  return colours[severity];
}

export function formatDate(value: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/London",
    timeZoneName: "short",
  }).format(new Date(value));
}

export function uniqueRegions(feed: SiteEntry[]): string[] {
  return Array.from(new Set(feed.map((site) => site.region).filter(Boolean) as string[])).sort();
}

export function uniqueDrivers(feed: SiteEntry[]): string[] {
  return Array.from(
    new Set(feed.flatMap((site) => site.drivers?.map((driver) => driver.name) ?? [])),
  ).sort();
}

export function filterSites(feed: SiteEntry[], filters: Filters): SiteEntry[] {
  const query = filters.query.trim().toLowerCase();

  return feed.filter((site) => {
    const severity = getSeverity(site.anomaly_score);
    const drivers = site.drivers ?? [];
    const searchable = [
      site.site_label,
      site.site_id,
      site.water_body_name,
      site.region,
      site.area,
      site.sub_area,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();

    return (
      (!filters.region || site.region === filters.region) &&
      (!filters.severity || severity === filters.severity) &&
      (!filters.driver || drivers.some((driver) => driver.name === filters.driver)) &&
      (!query || searchable.includes(query))
    );
  });
}

export function buildSummary(site: SiteEntry): string {
  if (site.summary) {
    return site.summary;
  }

  const severity = getSeverity(site.anomaly_score);
  const place = titleCaseSiteName(site.site_label);
  return `${place} is ranked #${site.anomaly_rank.toLocaleString("en-GB")} nationally for unusual chemistry. Severity: ${severity}. More detail will appear when the next narrated feed is generated.`;
}

export function topDriver(site: SiteEntry): string {
  const driver = site.drivers?.[0];
  return driver ? publicChemicalLabel(driver) : "No main driver listed";
}

export function eaMonitoringUrl(siteId: string): string {
  return `https://environment.data.gov.uk/water-quality/view/sampling-point/${encodeURIComponent(siteId)}`;
}

export function publicChemicalLabel(value: string | { label?: string; name: string }): string {
  const name = typeof value === "string" ? value : value.label || value.name;

  const label = name
    .replace("Alkalinity to pH 4.5 as CaCO3", "Alkalinity")
    .replace("Conductivity at 25 C", "Conductivity")
    .replace("Oxygen, Dissolved, % Saturation", "Oxygen saturation")
    .replace("Oxygen, Dissolved as O2", "Dissolved oxygen")
    .replace("Orthophosphate, reactive as P", "Phosphate")
    .replace("Nitrogen, Total Oxidised as N", "Oxidised nitrogen")
    .replace("Ammoniacal Nitrogen as N", "Ammonia-related nitrogen")
    .replace("Ammonia un-ionised as N", "Toxic ammonia")
    .replace("Temperature of Water", "Temperature");

  if (label === "pH") {
    return label;
  }

  return label.charAt(0).toUpperCase() + label.slice(1);
}
