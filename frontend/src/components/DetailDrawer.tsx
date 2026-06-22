import { AlertTriangle, CheckCircle2, Download, ExternalLink, Link2, X } from "lucide-react";
import type { ReactNode } from "react";
import { useState } from "react";
import {
  buildSummary,
  eaMonitoringUrl,
  getSeverity,
  getSeverityHex,
  publicChemicalLabel,
  titleCaseSiteName,
} from "../lib/feed";
import type { Driver, SeverityBand, SiteEntry } from "../types";
import {
  confidenceFillClass,
  confidenceFrequencyText,
  confidenceMeta,
  describePeerMatch,
  peerContextSentence,
  severityShortDescription,
  siteConfidence,
} from "../utils/labels";

interface DetailDrawerProps {
  featureNames: string[];
  onClose: () => void;
  site: SiteEntry | null;
}

function DetailDrawer({ featureNames, onClose, site }: DetailDrawerProps) {
  const [showScientificData, setShowScientificData] = useState(false);
  const [shareStatus, setShareStatus] = useState("");

  if (!site) {
    return null;
  }

  const severity = getSeverity(site.anomaly_score);
  const drivers = site.drivers ?? [];
  const confidence = siteConfidence(site);

  return (
    <div aria-modal="true" className="fixed inset-0 z-50" role="dialog">
      <button
        aria-label="Close site detail"
        className="absolute inset-0 cursor-default bg-ink/35"
        onClick={onClose}
        type="button"
      />
      <aside className="absolute right-0 top-0 flex h-full w-full max-w-2xl flex-col overflow-y-auto bg-white shadow-panel">
        <div className="sticky top-0 z-10 border-b border-slate-200 bg-white p-4 sm:p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="font-mono text-sm text-riverblue">{site.site_id}</p>
              <h2 className="mt-1 text-2xl font-semibold leading-tight text-ink">
                {site.display_name || titleCaseSiteName(site.site_label)}
              </h2>
              <p className="mt-2 text-xs leading-5 text-slate-400">
                This is an Environment Agency monitoring point name {"\u2014"} it describes where water samples are collected, not the source of any pollution
              </p>
            </div>
            <button
              aria-label="Close"
              className="rounded-md border border-slate-300 p-2 text-slate-700 hover:border-riverblue hover:text-riverblue"
              onClick={onClose}
              type="button"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        <div className="space-y-6 p-4 sm:p-5">
          <section aria-label="Site summary">
            <p className="whitespace-pre-line text-lg leading-relaxed text-slate-800">{buildSummary(site)}</p>
          </section>

          <div className="grid gap-3 sm:grid-cols-3">
            <Metric label="National rank" value={`Ranked #${site.anomaly_rank.toLocaleString("en-GB")} nationally`} />
            <Metric label="Severity" value={severityShortDescription(severity)} />
            <Metric label="Compared with" value={comparisonLabel(site)} />
          </div>

          <SimpleComparisonTable drivers={drivers} site={site} />

          <ChemicalPatternSection site={site} />

          <section>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <h3 className="text-base font-semibold text-ink">Main things to notice</h3>
              <label className="inline-flex w-fit items-center gap-2 rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700">
                <input
                  checked={showScientificData}
                  className="h-4 w-4 accent-riverblue"
                  onChange={(event) => setShowScientificData(event.target.checked)}
                  type="checkbox"
                />
                Show scientific data
              </label>
            </div>
            <div className="mt-3 space-y-3">
              {showScientificData ? <TechnicalDetails site={site} /> : null}
              {drivers.length > 0 ? (
                <>
                  {drivers.map((driver) => (
                    <ChemicalSignal
                      driver={driver}
                      key={driver.name}
                      showScientificData={showScientificData}
                    />
                  ))}
                  {site.is_cross_type ? <TypeMismatchSignal site={site} /> : null}
                </>
              ) : (
                <p className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slatecopy">
                  This site is outside the narrated top set, so chemical drivers are not listed yet.
                </p>
              )}
            </div>
          </section>

          <section>
            <h3 className="text-base font-semibold text-ink">Chemical profile</h3>
            <p className="mt-2 text-sm leading-6 text-slate-700">
              This chart compares this site with similar {site.score_reference || "peer-group"} monitoring sites.
              Red spikes show chemicals that are higher than expected.
            </p>
            <RadarChart drivers={drivers} featureNames={featureNames} severity={severity} />
          </section>

          <section className="grid gap-3 sm:grid-cols-2">
            <Info label="Water body" value={site.water_body_name || "Water body not classified"} />
            <Info label="Region" value={site.region || "Not listed"} />
            <Info label="Area" value={site.area || "Not listed"} />
            <Info label="WFD type" value={formatWfdType(site)} />
          </section>

          <section className="rounded-lg border border-slate-200 bg-slate-50 p-4">
            <div className="flex items-start gap-3">
              <AlertTriangle aria-hidden="true" className="mt-1 h-5 w-5 shrink-0 text-riverblue" />
              <p className="text-sm leading-6 text-slate-700">
                {peerContextSentence(site)} The black line on the chart represents expected
                chemistry for similar sites.
              </p>
            </div>
          </section>

          <DataQualitySection confidence={confidence} site={site} />

          <ActionsSection
            onDownload={() => downloadSiteData(site)}
            onShare={async () => {
              const copied = await copyShareLink(site.site_id);
              setShareStatus(copied ? "Link copied" : "Could not copy link");
              window.setTimeout(() => setShareStatus(""), 2000);
            }}
            shareStatus={shareStatus}
            site={site}
          />

          <section className="rounded-lg border border-slate-200 bg-slate-50 p-4">
            <p className="text-sm leading-6 text-slate-700">
              This analysis identifies unusual chemistry, not confirmed pollution. For official
              information about this site, view the Environment Agency record. To report a
              pollution incident, call the EA hotline: 0800 80 70 60.
            </p>
          </section>
        </div>
      </aside>
    </div>
  );
}

function DataQualitySection({
  confidence,
  site,
}: {
  confidence: ReturnType<typeof siteConfidence>;
  site: SiteEntry;
}) {
  const meta = confidenceMeta(site);

  return (
    <section className="rounded-lg border border-slate-200 bg-slate-50 p-4">
      <h3 className="text-base font-semibold text-ink">Data confidence</h3>
      <div className="mt-3 space-y-1 text-sm leading-6 text-slate-700">
        <p className="inline-flex items-center gap-2 font-semibold text-slate-800">
          <span aria-hidden="true" className={`h-2.5 w-2.5 rounded-full ${confidence.dotClass}`} />
          {confidence.label}
        </p>
        <p>{meta.chemicalMeasurements} across {meta.samplingDates}</p>
        <p>{meta.dateRange}</p>
        <p>{confidenceFrequencyText(site)}</p>
        <ConfidenceEvidenceBar site={site} />
      </div>
    </section>
  );
}

function ConfidenceEvidenceBar({ site }: { site: SiteEntry }) {
  const meta = confidenceMeta(site);

  return (
    <div className="pt-2">
      <div className="flex items-center gap-3">
        <div className="h-1 flex-1 rounded-full bg-slate-200">
          <div
            aria-hidden="true"
            className={`h-1 rounded-full ${confidenceFillClass(site)}`}
            style={{ width: `${meta.evidence.fillPercent}%` }}
          />
        </div>
        <span className="shrink-0 text-xs text-slate-400">{meta.evidence.label}</span>
      </div>
    </div>
  );
}

function ActionsSection({
  onDownload,
  onShare,
  shareStatus,
  site,
}: {
  onDownload: () => void;
  onShare: () => void;
  shareStatus: string;
  site: SiteEntry;
}) {
  return (
    <section>
      <h3 className="text-base font-semibold text-ink">Actions</h3>
      <div className="mt-3 flex flex-wrap gap-2">
        <ActionLink href={eaMonitoringUrl(site.site_id)}>
          View EA record
          <ExternalLink aria-hidden="true" className="h-4 w-4" />
        </ActionLink>
        <ActionLink href="https://www.gov.uk/report-an-environmental-incident">
          Report a concern
          <ExternalLink aria-hidden="true" className="h-4 w-4" />
        </ActionLink>
        <button
          className="inline-flex items-center gap-2 rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:border-riverblue hover:text-riverblue"
          onClick={onShare}
          type="button"
        >
          Share
          <Link2 aria-hidden="true" className="h-4 w-4" />
        </button>
        <button
          className="inline-flex items-center gap-2 rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:border-riverblue hover:text-riverblue"
          onClick={onDownload}
          type="button"
        >
          Download data
          <Download aria-hidden="true" className="h-4 w-4" />
        </button>
      </div>
      {shareStatus ? <p className="mt-2 text-sm font-semibold text-riverblue">{shareStatus}</p> : null}
    </section>
  );
}

function ActionLink({ children, href }: { children: ReactNode; href: string }) {
  return (
    <a
      className="inline-flex items-center gap-2 rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:border-riverblue hover:text-riverblue"
      href={href}
      rel="noreferrer"
      target="_blank"
    >
      {children}
    </a>
  );
}

async function copyShareLink(siteId: string): Promise<boolean> {
  const url = `${window.location.origin}?site=${encodeURIComponent(siteId)}`;
  try {
    await navigator.clipboard.writeText(url);
    return true;
  } catch {
    return false;
  }
}

function downloadSiteData(site: SiteEntry) {
  const blob = new Blob([JSON.stringify(site, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `river-signal-${site.site_id}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

function ChemicalPatternSection({ site }: { site: SiteEntry }) {
  const officialType = site.wfd_type || "Unknown";
  const resolvedType = firstKnown(site.wfd_type_resolved, site.dominant_peer_type) || "Unknown";
  const dominantPeerType = firstKnown(site.dominant_peer_type, site.wfd_type_resolved) || "other monitored";
  const showMismatch = Boolean(site.wfd_type && site.is_cross_type);

  return (
    <section>
      <h3 className="text-base font-semibold text-ink">Does this river match its type?</h3>
      <p className="mt-2 text-sm leading-6 text-slate-700">
        {describePeerMatch(site.peer_agreement_ratio)}
      </p>
      {showMismatch ? (
        <div className="mt-3 rounded-lg border border-amber-500 bg-amber-50 p-4 text-amber-950">
          <div className="flex items-start gap-3">
            <AlertTriangle aria-hidden="true" className="mt-1 h-5 w-5 shrink-0" />
            <p className="text-sm leading-6">
              This river looks out of character for its official {officialType} type. Its chemistry
              is closer to {dominantPeerType} rivers in the peer analysis. This may indicate
              external pollution pressure and should be investigated further.
            </p>
          </div>
        </div>
      ) : null}
      {!site.wfd_type && resolvedType !== "Unknown" ? (
        <div className="mt-3 rounded-lg border border-slate-300 bg-slate-50 p-4 text-slate-800">
          <p className="text-sm leading-6">
            This site has no official WFD classification, but its chemistry is consistent with{" "}
            {resolvedType} rivers based on peer analysis.
          </p>
        </div>
      ) : null}
      {!showMismatch && site.is_strong_agreement ? (
        <div className="mt-3 rounded-lg border border-emerald-600 bg-emerald-50 p-4 text-emerald-950">
          <div className="flex items-start gap-3">
            <CheckCircle2 aria-hidden="true" className="mt-1 h-5 w-5 shrink-0" />
            <p className="text-sm leading-6">
              Its chemistry broadly matches similar {officialType} rivers.
            </p>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function SimpleComparisonTable({ drivers, site }: { drivers: Driver[]; site: SiteEntry }) {
  const peerType = site.wfd_type_resolved || site.wfd_type || site.dominant_peer_type || "this river type";

  return (
    <section>
      <h3 className="text-base font-semibold text-ink">Simple comparison</h3>
      {drivers.length > 0 ? (
        <div className="mt-3 overflow-x-auto rounded-lg border border-slate-200">
          <table className="w-full min-w-[420px] border-collapse text-sm">
            <thead className="bg-slate-50 text-left text-slate-600">
              <tr>
                <th className="border-b border-slate-200 px-3 py-2 font-semibold">Measure</th>
                <th className="border-b border-slate-200 px-3 py-2 font-semibold">This river</th>
                <th className="border-b border-slate-200 px-3 py-2 font-semibold">
                  Typical for {peerType}
                </th>
              </tr>
            </thead>
            <tbody>
              {drivers.map((driver) => (
                <tr key={driver.name}>
                  <td className="border-t border-slate-200 px-3 py-2 text-ink">
                    {publicChemicalLabel(driver)}
                  </td>
                  <td className="border-t border-slate-200 px-3 py-2">
                    <DirectionBadge driver={driver} />
                  </td>
                  <td className="border-t border-slate-200 px-3 py-2">
                    <span className="inline-flex rounded-md border border-emerald-700 bg-emerald-50 px-2 py-1 font-semibold text-emerald-900">
                      Normal
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="mt-3 rounded-lg border border-emerald-700 bg-emerald-50 p-3 text-sm leading-6 text-emerald-950">
          No key chemical measures stand out from comparable rivers.
        </p>
      )}
    </section>
  );
}

function DirectionBadge({ driver }: { driver: Driver }) {
  const isHigh = driver.direction === "high";
  const label = isHigh ? "High" : "Low";

  return (
    <span
      className={`inline-flex rounded-md border px-2 py-1 font-semibold ${
        isHigh
          ? "border-red-700 bg-red-50 text-red-900"
          : "border-blue-700 bg-blue-50 text-blue-900"
      }`}
      title={isHigh ? "Higher than expected for similar rivers" : "Lower than expected for similar rivers"}
    >
      {label}
    </span>
  );
}

function TechnicalDetails({ site }: { site: SiteEntry }) {
  return (
    <div className="rounded-lg border border-slate-300 bg-slate-50 p-3">
      <p className="font-semibold text-ink">Technical details</p>
      <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
        <div>
          <dt className="font-semibold text-slate-600">Anomaly score</dt>
          <dd className="mt-1 font-mono text-lg text-ink">{site.anomaly_score.toFixed(2)}</dd>
        </div>
        <div>
          <dt className="font-semibold text-slate-600">Ranking method</dt>
          <dd className="mt-1 text-slate-800">Peer-group statistical comparison</dd>
        </div>
      </dl>
      <p className="mt-3 text-sm leading-6 text-slate-700">
        This is a statistical score used to rank how unusual the river's chemistry is compared
        with similar rivers. Higher scores mean more unusual chemistry.
      </p>
      <p className="mt-2 text-sm leading-6 text-slate-700">
        The scientific values below include full parameter names and z-scores for the main
        chemical drivers.
      </p>
    </div>
  );
}

function ChemicalSignal({
  driver,
  showScientificData,
}: {
  driver: Driver;
  showScientificData: boolean;
}) {
  return (
    <div className="rounded-lg border border-slate-200 p-3">
      {showScientificData ? (
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="font-semibold text-ink">{driver.name}</p>
            <p className="mt-2 text-sm leading-6 text-slate-700">{driver.description}</p>
          </div>
          <span className="font-mono text-sm text-slate-600">
            z {signedDriverZ(driver).toFixed(2)} {driver.unit ? `- ${driver.unit}` : ""}
          </span>
        </div>
      ) : (
        <>
          <p className="font-semibold text-ink">{publicDriverTitle(driver)}</p>
          <p className="mt-2 text-sm leading-6 text-slate-700">{publicDriverExplanation(driver)}</p>
        </>
      )}
    </div>
  );
}

function TypeMismatchSignal({ site }: { site: SiteEntry }) {
  return (
    <div className="rounded-lg border border-slate-200 p-3">
      <p className="font-semibold text-ink">The river looks unusual for its official type</p>
      <p className="mt-2 text-sm leading-6 text-slate-700">
        Its chemistry does not closely match most similar {site.wfd_type || site.score_reference || "peer-group"} rivers.
      </p>
    </div>
  );
}

function publicDriverTitle(driver: Driver): string {
  const label = publicChemicalLabel(driver);
  const direction = driver.direction === "high" ? "is high" : "is low";
  return `${label} ${direction}`;
}

function publicDriverExplanation(driver: Driver): string {
  const name = driver.name.toLowerCase();

  if (name.includes("un-ionised ammonia")) {
    return "This is the ammonia form most harmful to fish and river insects.";
  }
  if (name.includes("ammoniacal")) {
    return "This can be associated with sewage, slurry, landfill drainage, manure, or other organic waste.";
  }
  if (name.includes("nitrite")) {
    return "This reactive nitrogen form can be associated with sewage, organic pollution, or incomplete treatment.";
  }
  if (name.includes("nitrate") || name.includes("oxidised")) {
    return "This can be associated with fertiliser runoff, land drainage, wastewater, or other nutrient pressure.";
  }
  if (name.includes("phosphate")) {
    return "This nutrient can feed algal growth and put pressure on river life.";
  }
  if (name.includes("oxygen")) {
    return driver.direction === "low"
      ? "Low oxygen can stress fish, insects, and other river life."
      : "High oxygen can reflect strong plant or algal activity and should be checked with other evidence.";
  }
  if (name.includes("conductivity")) {
    return "This means the water contains more dissolved salts and minerals than expected.";
  }
  if (name.includes("ph")) {
    return "Large acidity or alkalinity differences can stress river wildlife.";
  }
  if (name.includes("temperature")) {
    return "Warm water can reduce oxygen availability and stress temperature-sensitive river life.";
  }
  return driver.description;
}

function comparisonLabel(site: SiteEntry): string {
  const reference = site.score_reference ? `similar ${site.score_reference} rivers` : "similar rivers";
  const count = site.score_peer_group_size?.toLocaleString("en-GB");
  return count ? `${count} ${reference}` : reference;
}

function firstKnown(...values: Array<string | null | undefined>): string | null {
  return values.find((value) => value && value !== "Unknown") ?? null;
}

function Metric({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-100 p-3">
      <p className="text-sm text-slate-500">{label}</p>
      <p className="mt-1 break-words text-lg font-semibold leading-snug text-slate-900 sm:text-xl">{value}</p>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 p-3">
      <p className="text-sm text-slate-500">{label}</p>
      <p className="mt-1 text-sm leading-6 text-ink">{value}</p>
    </div>
  );
}

function formatWfdType(site: SiteEntry): string {
  if (site.wfd_type_resolved) {
    return site.wfd_type_inferred ? `${site.wfd_type_resolved} (inferred from peers)` : site.wfd_type_resolved;
  }

  return site.score_reference || "Global comparison";
}

function RadarChart({
  drivers,
  featureNames,
  severity,
}: {
  drivers: Driver[];
  featureNames: string[];
  severity: SeverityBand;
}) {
  const names = featureNames.length
    ? featureNames
    : Array.from(new Set(drivers.map((driver) => driver.name)));
  const zByName = new Map(drivers.map((driver) => [driver.name, signedDriverZ(driver)]));
  const values = names.map((name) => zByName.get(name) ?? 0);
  const maxAbs = Math.max(2, Math.ceil(Math.max(...values.map((value) => Math.abs(value)), 0)));
  const size = 420;
  const center = size / 2;
  const outerRadius = 132;
  const zeroRadius = outerRadius / 2;
  const color = getSeverityHex(severity);
  const points = values
    .map((value, index) => {
      const angle = (Math.PI * 2 * index) / names.length - Math.PI / 2;
      const radius = ((value + maxAbs) / (maxAbs * 2)) * outerRadius;
      return `${center + Math.cos(angle) * radius},${center + Math.sin(angle) * radius}`;
    })
    .join(" ");

  const ringRadii = [0, 0.5, 1].map((ratio) => ratio * outerRadius);

  if (!names.length) {
    return (
      <p className="mt-3 border border-slate-200 bg-slate-50 p-3 text-sm text-slatecopy">
        No narrated driver data is available for this site yet.
      </p>
    );
  }

  return (
    <div className="mt-3 rounded-lg border border-slate-200 bg-white p-3">
      <div className="grid gap-2 text-sm text-slate-700 sm:grid-cols-2">
        <LegendItem swatchClass="bg-red-600" label="Red shape = this site" />
        <LegendItem swatchClass="border border-ink bg-white" label="Black line = expected chemistry for similar sites" />
        <LegendItem swatchClass="bg-slate-300" label="Further from the centre = higher than expected" />
        <LegendItem swatchClass="bg-red-100" label="Big red spikes = unusual readings" />
      </div>
      <svg
        className="mx-auto mt-3 h-auto w-full max-w-[460px]"
        role="img"
        aria-label="Chemical profile chart comparing this site with similar sites"
        viewBox={`0 0 ${size} ${size}`}
      >
        <title>Chemical profile chart</title>
        {ringRadii.map((radius) => (
          <circle
            cx={center}
            cy={center}
            fill="none"
            key={radius}
            r={radius}
            stroke={radius === zeroRadius ? "#111827" : "#d1d5db"}
            strokeDasharray={radius === zeroRadius ? "0" : "4 4"}
            strokeWidth={radius === zeroRadius ? 2 : 1}
          />
        ))}
        {names.map((name, index) => {
          const angle = (Math.PI * 2 * index) / names.length - Math.PI / 2;
          const x = center + Math.cos(angle) * outerRadius;
          const y = center + Math.sin(angle) * outerRadius;
          const labelX = center + Math.cos(angle) * (outerRadius + 34);
          const labelY = center + Math.sin(angle) * (outerRadius + 34);
          return (
            <g key={name}>
              <line x1={center} y1={center} x2={x} y2={y} stroke="#cbd5e1" strokeWidth={1} />
              <text
                dominantBaseline="middle"
                fill="#334155"
                fontSize={10}
                textAnchor={labelX < center - 10 ? "end" : labelX > center + 10 ? "start" : "middle"}
                x={labelX}
                y={labelY}
              >
                {publicChemicalLabel(name)}
              </text>
            </g>
          );
        })}
        <polygon fill={color} fillOpacity={0.25} points={points} stroke={color} strokeWidth={2.5} />
        {values.map((value, index) => {
          const angle = (Math.PI * 2 * index) / names.length - Math.PI / 2;
          const radius = ((value + maxAbs) / (maxAbs * 2)) * outerRadius;
          return (
            <circle
              cx={center + Math.cos(angle) * radius}
              cy={center + Math.sin(angle) * radius}
              fill="#ffffff"
              key={`${names[index]}-${value}`}
              r={3}
              stroke={color}
              strokeWidth={2}
            />
          );
        })}
        <text fill="#111827" fontSize={11} fontWeight={700} x={center + zeroRadius + 8} y={center - 6}>
          expected peer chemistry
        </text>
        <text fill="#64748b" fontSize={10} x={center - outerRadius} y={center + outerRadius + 30}>
          Further from the centre means higher than expected
        </text>
      </svg>
    </div>
  );
}

function LegendItem({ label, swatchClass }: { label: string; swatchClass: string }) {
  return (
    <div className="flex items-center gap-2">
      <span aria-hidden="true" className={`h-3 w-3 shrink-0 rounded-sm ${swatchClass}`} />
      <span>{label}</span>
    </div>
  );
}

function signedDriverZ(driver: Driver): number {
  return driver.direction === "low" ? -Math.abs(driver.z) : Math.abs(driver.z);
}

export default DetailDrawer;
