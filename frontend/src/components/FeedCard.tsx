import { AlertTriangle, ArrowDown, ArrowUp } from "lucide-react";
import {
  buildSummary,
  getSeverity,
  getSeverityClasses,
  getSeverityDot,
  publicChemicalLabel,
  titleCaseSiteName,
  topDriver,
} from "../lib/feed";
import type { Driver, SeverityBand, SiteEntry } from "../types";
import { formatDistanceKm } from "../utils/distance";

interface FeedCardProps {
  onOpen: () => void;
  site: SiteEntry;
}

function FeedCard({ onOpen, site }: FeedCardProps) {
  const severity = getSeverity(site.anomaly_score);
  const drivers = site.drivers ?? [];
  const distanceKm = "distanceKm" in site ? site.distanceKm : null;
  const showMismatch = Boolean(site.wfd_type && site.is_cross_type);
  const mismatchTooltip = `This river looks chemically out of character for its official ${site.wfd_type || "Unknown"} type. Further investigation is needed.`;

  return (
    <article
      className={`rounded-lg border border-l-4 bg-white transition-shadow duration-200 hover:shadow-md ${
        showMismatch ? "border-amber-400" : "border-slate-200"
      } ${severityBorderClass(severity)}`}
    >
      <button className="block w-full p-4 text-left sm:p-5" onClick={onOpen} type="button">
        <div className="flex flex-col gap-4 md:flex-row md:items-start">
          <div className="flex shrink-0 items-center gap-3 md:w-32 md:flex-col md:items-start">
            <span className="inline-flex min-w-16 justify-center rounded-md border border-ink bg-ink px-3 py-1 text-sm font-semibold text-white">
              #{site.anomaly_rank.toLocaleString("en-GB")}
            </span>
            <span
              className={`inline-flex items-center gap-2 rounded-md border px-3 py-1 text-sm font-semibold ${getSeverityClasses(
                severity,
              )}`}
            >
              <span aria-hidden="true" className={`h-2 w-2 rounded-full ${getSeverityDot(severity)}`} />
              {severity}
            </span>
          </div>

          <div className="min-w-0 flex-1">
            <div className="flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-xl font-semibold leading-snug text-ink">
                    {titleCaseSiteName(site.site_label)}
                  </h2>
                  {showMismatch ? (
                    <span
                      className="inline-flex items-center gap-1.5 rounded-md border border-amber-600 bg-amber-100 px-2.5 py-1 text-sm font-semibold text-amber-950"
                      title={mismatchTooltip}
                    >
                      <AlertTriangle aria-hidden="true" className="h-4 w-4" />
                      Looks out of character
                    </span>
                  ) : null}
                </div>
                <p className="mt-1 text-sm text-slatecopy">
                  {site.water_body_name || "Water body not classified"} - {site.region || "Region not listed"}
                </p>
              </div>
              <div className="space-y-1 lg:text-right">
                {typeof distanceKm === "number" ? (
                  <p className="font-mono text-sm font-semibold text-riverblue">
                    {formatDistanceKm(distanceKm)}
                  </p>
                ) : null}
                <p className="text-sm text-slate-600">
                  {cardComparisonLabel(site)}
                </p>
              </div>
            </div>

            <p className="mt-4 line-clamp-3 text-base leading-7 text-slate-700">{buildSummary(site)}</p>

            <div className="mt-4 flex flex-wrap gap-2">
              {drivers.length > 0 ? (
                drivers.map((driver) => <DriverPill driver={driver} key={`${site.site_id}-${driver.name}`} />)
              ) : (
                <span className="rounded-md border border-slate-300 bg-slate-50 px-2.5 py-1 text-sm text-slate-600">
                  {topDriver(site)}
                </span>
              )}
            </div>
          </div>
        </div>
      </button>
    </article>
  );
}

function severityBorderClass(severity: SeverityBand): string {
  return {
    Extreme: "border-l-red-800",
    High: "border-l-red-700",
    Moderate: "border-l-amber-600",
    Lower: "border-l-emerald-700",
  }[severity];
}

function cardComparisonLabel(site: SiteEntry): string {
  const count = site.score_peer_group_size?.toLocaleString("en-GB");
  if (count) {
    return `Compared with ${count} similar rivers`;
  }

  return site.score_reference ? `Compared with ${site.score_reference} rivers` : "Compared with similar rivers";
}

export function DriverPill({ driver }: { driver: Driver }) {
  const isHigh = driver.direction === "high";

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-sm ${
        isHigh
          ? "border-red-200 bg-red-50 text-red-900"
          : "border-blue-200 bg-blue-50 text-blue-900"
      }`}
    >
      {isHigh ? (
        <ArrowUp aria-label="High" className="h-3.5 w-3.5" />
      ) : (
        <ArrowDown aria-label="Low" className="h-3.5 w-3.5" />
      )}
      {publicChemicalLabel(driver)}
    </span>
  );
}

export default FeedCard;
