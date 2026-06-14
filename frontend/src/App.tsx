import {
  ChevronDown,
  ExternalLink,
  Filter,
  InfoIcon,
  List,
  Map as MapIcon,
  Search,
} from "lucide-react";
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import DetailDrawer from "./components/DetailDrawer";
import FeedCard from "./components/FeedCard";
import PostcodeSearch from "./components/PostcodeSearch";
import {
  filterSites,
  loadRankedFeed,
  uniqueDrivers,
  uniqueRegions,
} from "./lib/feed";
import type {
  Filters,
  GeoPoint,
  LocalSearchState,
  LocalSiteEntry,
  RankedFeed,
  SiteEntry,
} from "./types";
import { nearestSites } from "./utils/distance";

type ViewMode = "feed" | "map" | "about";

const MapView = lazy(() => import("./components/MapView"));
const LocalMapPreview = lazy(() =>
  import("./components/MapView").then((module) => ({ default: module.LocalMapPreview })),
);

const initialFilters: Filters = {
  region: "",
  severity: "",
  driver: "",
  query: "",
};

const initialLocalSearch: LocalSearchState = {
  error: null,
  label: "",
  location: null,
  results: [],
  status: "idle",
};

function App() {
  const [data, setData] = useState<RankedFeed | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<Filters>(initialFilters);
  const [localSearch, setLocalSearch] = useState<LocalSearchState>(initialLocalSearch);
  const [selectedSite, setSelectedSite] = useState<SiteEntry | null>(null);
  const [view, setView] = useState<ViewMode>("feed");

  useEffect(() => {
    loadRankedFeed()
      .then(setData)
      .catch((loadError: Error) => setError(loadError.message));
  }, []);

  const localSearchActive = localSearch.status === "ready";
  const baseSites = localSearchActive ? localSearch.results : data?.feed ?? [];
  const regions = useMemo(() => uniqueRegions(baseSites), [baseSites]);
  const drivers = useMemo(() => uniqueDrivers(baseSites), [baseSites]);
  const filteredSites = useMemo(
    () => filterSites(baseSites, filters),
    [baseSites, filters],
  );
  const visibleSites = localSearchActive ? filteredSites : filteredSites.slice(0, 250);
  const hasFilters = Object.values(filters).some(Boolean);

  function handleLocationFound(location: GeoPoint, label: string) {
    if (!data) {
      setLocalSearch({
        ...initialLocalSearch,
        error: "The river feed is still loading. Try the local search again in a moment.",
        status: "error",
      });
      return;
    }

    setLocalSearch({ ...initialLocalSearch, label, location, status: "loading" });

    const results = nearestSites(data.feed, location, 10, 50);
    setLocalSearch({
      error: results.length === 0 ? "No monitored rivers found nearby." : null,
      label,
      location,
      results,
      status: "ready",
    });
    setView("feed");
  }

  function handleLocalSearchError(message: string) {
    setLocalSearch({
      ...initialLocalSearch,
      error: message,
      status: "error",
    });
  }

  function resetAllFilters() {
    setFilters(initialFilters);
    setLocalSearch(initialLocalSearch);
  }

  return (
    <main className="min-h-screen bg-paper text-ink">
      <Header view={view} onViewChange={setView} />

      <section className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-col gap-8 px-4 py-6 sm:px-6 lg:px-8">
          <header className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-4xl">
              <p className="max-w-4xl text-2xl font-semibold leading-snug text-slate-900 sm:text-3xl">
                Explore freshwater river chemistry across England, with unusual sites ranked, compared, and explained in plain English.
              </p>
              <p className="mt-2 max-w-4xl text-sm leading-6 text-slatecopy sm:text-base">
                Covers 8,857 Environment Agency monitoring sites on rivers and running surface waters,
                analysed across 12 chemical indicators. Does not include estuaries, canals, lakes,
                coastal waters, groundwater, or drinking water quality.
              </p>
            </div>
            <div className="grid grid-cols-3 gap-3 lg:min-w-[420px]">
              <Metric
                label="Total sites"
                title="The number of Environment Agency river monitoring points included in this analysis."
                value={data?.total_sites.toLocaleString("en-GB") ?? "..."}
              />
              <Metric
                label="Flagged"
                title="Sites in the top 5% nationally for unusual chemistry. These are the sites where water quality differs most from what is expected for that type of river."
                value={data?.flagged_sites.toLocaleString("en-GB") ?? "..."}
              />
              <Metric
                label="Fully profiled"
                title="Sites with a complete chemical health summary explaining what's normal or unusual about their water quality."
                value={data?.total_sites.toLocaleString("en-GB") ?? "..."}
              />
            </div>
          </header>

          <div className="flex flex-col gap-3 border-t border-slate-200 pt-5 sm:flex-row sm:items-center sm:justify-between">
            {data ? (
              <p className="inline-flex items-center gap-2 text-sm text-slate-600">
                <span aria-hidden="true" className="h-2.5 w-2.5 rounded-full bg-emerald-500" />
                {formatDataCoverage(data)}
              </p>
            ) : null}
          </div>
        </div>
      </section>

      {view === "feed" ? (
        <section className="mx-auto grid max-w-7xl gap-6 px-4 py-6 sm:px-6 lg:grid-cols-[320px_1fr] lg:px-8">
          <aside className="space-y-4 lg:sticky lg:top-24 lg:self-start">
            <PostcodeSearch
              disabled={!data}
              error={localSearch.status === "error" ? localSearch.error : null}
              hasActiveSearch={localSearch.status === "ready"}
              isLoading={localSearch.status === "loading"}
              onClear={resetAllFilters}
              onError={handleLocalSearchError}
              onLocationFound={handleLocationFound}
            />
            <FilterPanel
              drivers={drivers}
              filters={filters}
              onChange={setFilters}
              onReset={() => setFilters(initialFilters)}
              onResetAll={resetAllFilters}
              regions={regions}
              resultCount={filteredSites.length}
              hasFilters={hasFilters}
            />
          </aside>

          <section aria-label="Ranked river chemistry feed" className="min-w-0">
            {error ? <Notice tone="error">{error}</Notice> : null}
            {!data && !error ? <Notice>Loading the ranked chemistry feed...</Notice> : null}
            {localSearchActive ? (
              <LocalResultsHeader
                filteredCount={filteredSites.length}
                label={localSearch.label}
                onClear={() => setLocalSearch(initialLocalSearch)}
                onViewMap={() => setView("map")}
                results={localSearch.results}
              />
            ) : null}
            {data && filteredSites.length === 0 ? (
              <Notice>
                {localSearchActive
                  ? "No monitored rivers found nearby with those filters."
                  : "No sites match those filters. Try widening the search."}
              </Notice>
            ) : null}

            <div className="flex flex-col gap-6">
              {visibleSites.map((site) => (
                <FeedCard key={site.site_id} site={site} onOpen={() => setSelectedSite(site)} />
              ))}
            </div>

            {filteredSites.length > visibleSites.length ? (
              <p className="mt-6 border border-slate-200 bg-white px-4 py-3 text-sm text-slatecopy">
                Showing the first {visibleSites.length.toLocaleString("en-GB")} matching sites to
                keep the feed quick. Narrow the filters to inspect the rest.
              </p>
            ) : null}
          </section>
        </section>
      ) : null}

      {view === "map" ? (
        <Suspense fallback={<LoadingPanel label="Loading the map..." />}>
          <MapView
            regions={regions}
            sites={baseSites}
            onOpenSite={setSelectedSite}
            isLoading={!data && !error}
            error={error}
          />
        </Suspense>
      ) : null}

      {view === "about" ? <AboutSection /> : null}

      <Footer />
      <DetailDrawer
        featureNames={data?.feature_cols ?? []}
        site={selectedSite}
        onClose={() => setSelectedSite(null)}
      />
    </main>
  );
}

interface HeaderProps {
  onViewChange: (view: ViewMode) => void;
  view: ViewMode;
}

function Header({ onViewChange, view }: HeaderProps) {
  return (
    <div className="sticky top-0 z-30 border-b border-slate-200 bg-white/95 backdrop-blur">
      <div className="h-1 bg-riverblue" />
      <div className="mx-auto flex max-w-7xl flex-col gap-3 px-4 py-3 sm:px-6 md:flex-row md:items-center md:justify-between lg:px-8">
        <button
          className="w-fit text-left text-xl font-semibold text-ink"
          onClick={() => onViewChange("feed")}
          type="button"
        >
          River Signal
        </button>
        <nav aria-label="Primary navigation" className="flex flex-wrap gap-2">
          <NavButton icon={<List className="h-4 w-4" />} isActive={view === "feed"} onClick={() => onViewChange("feed")}>
            Feed
          </NavButton>
          <NavButton icon={<MapIcon className="h-4 w-4" />} isActive={view === "map"} onClick={() => onViewChange("map")}>
            Map
          </NavButton>
          <NavButton
            icon={<InfoIcon className="h-4 w-4" />}
            isActive={view === "about"}
            onClick={() => onViewChange("about")}
          >
            About
          </NavButton>
        </nav>
      </div>
    </div>
  );
}

function NavButton({
  children,
  icon,
  isActive,
  onClick,
}: {
  children: ReactNode;
  icon: ReactNode;
  isActive: boolean;
  onClick: () => void;
}) {
  return (
    <button
      aria-current={isActive ? "page" : undefined}
      className={`inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm font-semibold ${
        isActive
          ? "border-riverblue bg-riverblue text-white"
          : "border-slate-300 bg-white text-slate-700 hover:border-riverblue hover:text-riverblue"
      }`}
      onClick={onClick}
      type="button"
    >
      {icon}
      {children}
    </button>
  );
}

interface MetricProps {
  label: string;
  title?: string;
  value: string;
}

function Metric({ label, title, value }: MetricProps) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-100 p-3" title={title}>
      <p className="inline-flex items-center gap-1.5 text-sm text-slate-500">
        {label}
        {title ? <InfoIcon aria-hidden="true" className="h-3.5 w-3.5" /> : null}
      </p>
      <p className="mt-1 text-2xl font-semibold text-slate-900">{value}</p>
    </div>
  );
}

function LoadingPanel({ label }: { label: string }) {
  return (
    <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      <div className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700">
        <span
          aria-hidden="true"
          className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-riverblue"
        />
        {label}
      </div>
    </div>
  );
}

function formatDataCoverage(data: RankedFeed): string {
  const start = data.data_period_start ? formatMonthYear(data.data_period_start) : "the available record";
  const end = data.data_period_end ? formatMonthYear(data.data_period_end) : "latest available data";
  return `Data covers: ${start} - ${end} | Last processed: ${formatProcessDate(data.generated_at)}`;
}

function formatMonthYear(value: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    month: "short",
    year: "numeric",
    timeZone: "Europe/London",
  }).format(new Date(value));
}

function formatProcessDate(value: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "Europe/London",
  }).format(new Date(value));
}

interface FilterPanelProps {
  drivers: string[];
  filters: Filters;
  hasFilters: boolean;
  onChange: (filters: Filters) => void;
  onReset: () => void;
  onResetAll: () => void;
  regions: string[];
  resultCount: number;
}

function FilterPanel({
  drivers,
  filters,
  hasFilters,
  onChange,
  onReset,
  onResetAll,
  regions,
  resultCount,
}: FilterPanelProps) {
  return (
    <form className="rounded-lg border border-slate-200 bg-white p-4" onSubmit={(event) => event.preventDefault()}>
      <div className="flex items-center gap-2">
        <Filter aria-hidden="true" className="h-4 w-4 text-riverblue" />
        <h2 className="text-lg font-semibold text-ink">Refine the feed</h2>
      </div>
      <p className="mt-2 text-sm text-slatecopy">
        {resultCount.toLocaleString("en-GB")} sites match the current view.
      </p>

      <label className="mt-5 block text-sm font-semibold text-ink" htmlFor="site-search">
        Search
      </label>
      <div className="mt-2 flex items-center rounded-md border border-slate-300 bg-white px-3 focus-within:border-riverblue focus-within:ring-2 focus-within:ring-riverblue/20">
        <Search aria-hidden="true" className="h-4 w-4 shrink-0 text-slate-500" />
        <input
          className="min-w-0 flex-1 bg-transparent px-2 py-2 text-sm outline-none"
          id="site-search"
          onChange={(event) => onChange({ ...filters, query: event.target.value })}
          placeholder="Site, river, water body"
          type="search"
          value={filters.query}
        />
      </div>

      <Select
        label="Region"
        onChange={(value) => onChange({ ...filters, region: value })}
        options={regions}
        value={filters.region}
      />
      <Select
        label="Severity"
        onChange={(value) => onChange({ ...filters, severity: value })}
        options={["Extreme", "High", "Moderate", "Lower"]}
        value={filters.severity}
      />
      <Select
        label="Main chemical signal"
        onChange={(value) => onChange({ ...filters, driver: value })}
        options={drivers}
        value={filters.driver}
      />

      <button
        className="mt-5 w-full rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 transition hover:border-riverblue hover:text-riverblue disabled:cursor-not-allowed disabled:opacity-50"
        disabled={!hasFilters}
        onClick={onReset}
        type="button"
      >
        Clear filters
      </button>
      <button
        className="mt-2 w-full rounded-md border border-riverblue bg-riverblue px-3 py-2 text-sm font-semibold text-white transition hover:bg-riverblue-dark"
        onClick={onResetAll}
        type="button"
      >
        Reset all filters
      </button>
    </form>
  );
}

interface SelectProps {
  label: string;
  onChange: (value: string) => void;
  options: string[];
  value: string;
}

function Select({ label, onChange, options, value }: SelectProps) {
  const id = label.toLowerCase().replace(/\s+/g, "-");

  return (
    <>
      <label className="mt-4 block text-sm font-semibold text-ink" htmlFor={id}>
        {label}
      </label>
      <select
        className="mt-2 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-ink outline-none focus:border-riverblue focus:ring-2 focus:ring-riverblue/20"
        id={id}
        onChange={(event) => onChange(event.target.value)}
        value={value}
      >
        <option value="">All</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </>
  );
}

function Notice({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "error" }) {
  return (
    <div
      className={`mb-4 rounded-lg border px-4 py-3 text-sm ${
        tone === "error"
          ? "border-red-300 bg-red-50 text-red-900"
          : "border-slate-200 bg-white text-slate-700"
      }`}
    >
      {children}
    </div>
  );
}

interface LocalResultsHeaderProps {
  filteredCount: number;
  label: string;
  onClear: () => void;
  onViewMap: () => void;
  results: LocalSiteEntry[];
}

function LocalResultsHeader({
  filteredCount,
  label,
  onClear,
  onViewMap,
  results,
}: LocalResultsHeaderProps) {
  return (
    <section className="mb-4 rounded-lg border border-slate-200 bg-white">
      <div className="grid gap-4 p-4 lg:grid-cols-[1fr_280px]">
        <div>
          <p className="font-mono text-sm text-riverblue">Local Rivers</p>
          <div className="mt-1 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h2 className="text-2xl font-semibold leading-tight text-ink">
                Rivers near {label}
              </h2>
              <p className="mt-2 text-sm leading-6 text-slatecopy">
                Showing {filteredCount.toLocaleString("en-GB")} of {results.length.toLocaleString("en-GB")} monitored
                sites within 50 km, sorted by distance.
              </p>
            </div>
            <button
              className="w-fit rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 transition hover:border-riverblue hover:text-riverblue"
              onClick={onClear}
              type="button"
            >
              Clear local search
            </button>
          </div>
        </div>
        <Suspense fallback={<MapPreviewFallback />}>
          <LocalMapPreview onViewMap={onViewMap} sites={results} />
        </Suspense>
      </div>
    </section>
  );
}

function MapPreviewFallback() {
  return (
    <div className="flex h-36 items-center justify-center rounded-lg border border-slate-300 bg-slate-50 text-sm text-slatecopy">
      Loading map preview...
    </div>
  );
}

const glossaryTerms = [
  {
    term: "Anomaly score",
    definition:
      "A number measuring how different a site's chemistry is from what you would expect for similar sites. Higher means more unusual. A site ranked #1 has the most unusual chemistry in the country.",
  },
  {
    term: "Chemical fingerprint",
    definition:
      "A set of 12 chemical measurements that together describe the water quality profile of a site. Like a fingerprint, no two sites are identical, but similar sites share common patterns.",
  },
  {
    term: "Common core panel",
    definition:
      "The 12 chemical measurements used in the analysis: temperature, pH, alkalinity, conductivity, dissolved oxygen (concentration and saturation), nitrate, nitrite, total oxidised nitrogen, ammoniacal nitrogen, un-ionised ammonia, and orthophosphate. These were chosen because they are measured consistently across most sites.",
  },
  {
    term: "Conductivity",
    definition:
      "A measure of how many dissolved salts and minerals are in the water. High conductivity can indicate sewage effluent, road runoff, or industrial discharge. Measured in microsiemens per centimetre (uS/cm).",
  },
  {
    term: "Dissolved oxygen",
    definition:
      "The amount of oxygen available in the water for fish and other aquatic life. Low dissolved oxygen is one of the clearest signs of pollution, often from sewage or organic waste that consumes oxygen as it decomposes.",
  },
  {
    term: "Driver",
    definition:
      "The specific chemical measurement(s) causing a site to score as anomalous. If a site is flagged, its drivers tell you which chemicals are unusual and in which direction, higher or lower than expected.",
  },
  {
    term: "Flagged site",
    definition:
      "A site whose anomaly score is in the top 5% nationally. There are currently 443 flagged sites out of 8,857 total.",
  },
  {
    term: "Nitrogen compounds",
    definition:
      "Different forms of nitrogen in water: nitrate, nitrite, ammoniacal nitrogen, total oxidised nitrogen, and un-ionised ammonia. Elevated nitrogen usually comes from agricultural fertiliser, sewage, or both. Un-ionised ammonia is the form most toxic to fish. Nitrite is unstable and often indicates active pollution or incomplete treatment.",
  },
  {
    term: "Orthophosphate",
    definition:
      "A form of phosphorus. Elevated phosphate is one of the main drivers of eutrophication, where excess nutrients cause algal blooms that suffocate other aquatic life. Common sources include sewage treatment works and agricultural runoff.",
  },
  {
    term: "Peer group",
    definition:
      "The set of similar sites a given site is compared against. Sites are grouped by their WFD type, for example, low, small, calcareous means a lowland, small, chalk-geology river. A site is only considered anomalous if it differs from sites of the same type, not from all sites everywhere.",
  },
  {
    term: "Severity band",
    definition:
      "A plain language label derived from the anomaly score: Extreme, High, Moderate, or Low. Used to make scores easier to interpret without knowing the underlying numbers.",
  },
  {
    term: "WFD type (Water Framework Directive typology)",
    definition:
      "A classification system that groups river sites by their natural characteristics: altitude, size, and geology. Sites of the same WFD type are expected to have similar baseline chemistry.",
  },
  {
    term: "z-score",
    definition:
      "A statistical measure of how far a value is from the average of its group, expressed in standard deviations. A z-score of +3 means the value is 3 standard deviations above the group average. In River Signal, z-scores are calculated for each chemical feature relative to the site's peer group. Scores above +2 or below -2 are flagged as notable.",
  },
];

const methodologySteps = [
  "Raw observations are downloaded from the Environment Agency's open data API.",
  "Records are filtered to river and running surface water samples only.",
  "Values reported as below detection limits, for example <0.01, are replaced with half the detection limit.",
  "Observations are aggregated to site level using the median value per determinand.",
  "Sites with fewer than 75% of the 12 core measurements are excluded.",
  "Each site receives a 12-dimensional chemical fingerprint.",
  "Sites are grouped by WFD typology and scored by deviation from their peer group median.",
  "Sites are ranked nationally by composite anomaly score.",
  "Anomaly drivers are identified per site, using features with z-scores exceeding 2 standard deviations.",
  "Plain English summaries are generated for the top-scoring sites.",
];

function AboutSection() {
  return (
    <section className="mx-auto max-w-5xl px-4 py-8 sm:px-6 lg:px-8">
      <div className="space-y-8">
        <AboutBlock title="What is River Signal?">
          <p>
            River Signal turns routine water quality monitoring data into a ranked list of the
            river sites in England with the most unusual chemistry. It exists because the data is
            public but the insight is not.
          </p>
          <p>
            The Environment Agency monitors thousands of river sites across England, measuring
            chemicals such as ammonia, phosphate, dissolved oxygen, and nitrate. The raw data is
            openly available, but its public value depends on whether people can interpret it.
            River Signal turns complex monitoring data into clear rankings, comparisons, and
            plain English explanations, helping more people see where water quality looks unusual
            and where further investigation may be needed.
          </p>
          <p>
            River Signal answers those questions. It scores every monitored site by comparing its
            chemistry against similar sites nationally, flags the ones that stand out, and explains
            what is unusual and why it matters, in plain English.
          </p>
          <p>
            It is designed to make river chemistry data useful beyond specialist circles:
            for regulators prioritising investigations, water companies tracking emerging problems,
            journalists and MPs looking for evidence they can cite, and residents who want to
            understand what is happening in their local river.
          </p>

        </AboutBlock>

        <AboutBlock title="Where does the data come from?">
          <p>
            All data comes from the Environment Agency's open water quality monitoring archive.
            River Signal currently analyses 6.88 million observations across 8,857 river sites,
            covering the period 2015 to 2024. The data includes 12 chemical measurements that
            together form a "fingerprint" of each site's water quality.
          </p>
          <p>
            No private or proprietary data is used. The analysis runs entirely on publicly
            available information.
          </p>
        </AboutBlock>

        <AboutBlock title="How does the scoring work?">
          <p>
            Each river site in England has a Water Framework Directive (WFD) classification that
            describes the kind of river it is: whether it is lowland or upland, small or large,
            and flowing through geology such as chalk or sandstone. Sites of the same type are
            expected to have broadly similar chemistry.
          </p>

          <p>
            The 12 chemical indicators used are: temperature, pH, alkalinity, conductivity,
            dissolved oxygen (both concentration and saturation), nitrate, nitrite, total
            oxidised nitrogen, ammoniacal nitrogen, un-ionised ammonia, and orthophosphate.
            These were selected because they are measured consistently across most monitoring
            sites and together capture the key dimensions of river water quality.
          </p>

          <p>
            River Signal compares each site's chemistry with other sites of the same WFD type
            nationally, measuring differences across all 12 chemical indicators at the same time.
            A site with unusually high ammonia compared with other lowland chalk streams, for
            example, will score higher than one with typical levels.
          </p>

          <p>
            For WFD types with fewer than 30 sites, where group statistics are less reliable,
            River Signal compares the site with the 20 geographically nearest sites instead.
          </p>

          <p>
            As a separate check, River Signal also identifies each site's closest chemical peers,
            regardless of WFD classification. This uses a hybrid method that combines dimensionality
            reduction with full 12-indicator distance measurement.
          </p>

          <p>
            If a site's nearest chemical peers mostly belong to a different WFD type from its
            official classification, this suggests the site may be behaving more like a different
            river type and should be looked at more closely.
          </p>

          <p>
            Sites are then ranked nationally by their overall anomaly score. The highest-ranking
            sites are flagged and given a plain English explanation of which chemical signals are
            driving the anomaly.
          </p>

          <p>
            The method does not diagnose the cause of a problem. It identifies where something
            unusual is happening and describes the chemical pattern. Determining whether the cause
            is a sewage discharge, agricultural runoff, industrial input, or something else
            requires further investigation. River Signal tells you where to look and what to look
            for.
          </p>
        </AboutBlock>

        <AboutBlock title="What River Signal is not">
          <p>
            It is not a real time alert system. The data is updated periodically, not live. For
            real time sewage overflow alerts, Surfers Against Sewage operates the Safer Seas and
            Rivers Service.
          </p>
          <p>
            It is not a compliance tool. It does not measure sites against regulatory standards or
            WFD status objectives. It identifies statistical outliers, not regulatory failures,
            though the two often overlap.
          </p>
          <p>
            It is not affiliated with any water company, regulator, or government body. This is
            independent research.
          </p>
        </AboutBlock>

        <AboutBlock title="Methodology">
          <div className="grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
            <ol className="space-y-3">
              {methodologySteps.map((step, index) => (
                <li className="flex gap-3" key={step}>
                  <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center border border-slate-300 font-mono text-xs font-semibold text-riverblue">
                    {index + 1}
                  </span>
                  <span>{step}</span>
                </li>
              ))}
            </ol>
            <div className="space-y-4 border border-slate-200 bg-slate-50 p-4">
              <h3 className="text-base font-semibold text-ink">Limitations</h3>
              <p>
                The analysis uses monitoring data as reported by the Environment Agency. Sampling
                frequency varies between sites; some are monitored monthly, others only a few times
                per year. Sites with very few observations may produce less reliable scores.
              </p>
              <p>
                The scoring identifies statistical outliers, not confirmed pollution events. An
                anomalous chemical profile can have natural explanations, such as geology, season,
                or hydrology, as well as human causes.
              </p>
              <p>
                Temporal analysis, detecting sites that are getting worse over time, is not yet
                implemented but is planned for a future version.
              </p>
            </div>
          </div>
        </AboutBlock>

        <AboutBlock title="What comes next">
          <p>
            River Signal currently covers freshwater river chemistry. The same approach can be
            applied to other monitored environments: estuaries, canals, lakes, coastal waters, and
            groundwater. Future versions may incorporate additional data sources including sewage
            discharge records, agricultural land use, industrial permits, and ecological survey
            results, to move from identifying anomalies to explaining their probable causes.
          </p>
          <p>
            The underlying research methodology, UMAP based chemical fingerprinting of river
            monitoring data, is currently under peer review at Water Research.
          </p>
        </AboutBlock>

        <AboutBlock title="Who built this?">
          <p>
            River Signal was built by Sohail Syed, a data scientist working in the UK water
            industry. The analysis was conducted independently, on personal time and equipment,
            using publicly available data. The code is open source, and the project is not
            affiliated with or endorsed by any employer.
          </p>

          <a
            className="inline-flex items-center gap-2 rounded-md border border-riverblue bg-riverblue px-4 py-2 text-sm font-semibold text-white hover:bg-riverblue-dark"
            href="https://github.com/syedameersohail/River-Chemical-Fingerprints-England"
            rel="noreferrer"
            target="_blank"
          >
            GitHub repository
            <ExternalLink aria-hidden="true" className="h-4 w-4" />
          </a>
        </AboutBlock>

        <AboutBlock title="Glossary">
          <div className="divide-y divide-slate-200 border border-slate-200">
            {glossaryTerms.map((item) => (
              <details className="group bg-white" key={item.term}>
                <summary className="flex cursor-pointer list-none items-center justify-between gap-4 px-4 py-3 text-left text-base font-semibold text-ink hover:bg-slate-50">
                  <span>{item.term}</span>
                  <ChevronDown
                    aria-hidden="true"
                    className="h-4 w-4 shrink-0 text-slate-500 transition group-open:rotate-180"
                  />
                </summary>
                <p className="px-4 pb-4 text-sm leading-7 text-slate-700">{item.definition}</p>
              </details>
            ))}
          </div>
        </AboutBlock>
      </div>
    </section>
  );
}

function AboutBlock({ children, title }: { children: ReactNode; title: string }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5 sm:p-7">
      <h2 className="text-2xl font-semibold text-ink">{title}</h2>
      <div className="mt-5 space-y-5 text-base leading-8 text-slate-700">{children}</div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="border-t border-slate-200 bg-white">
      <div className="mx-auto max-w-7xl px-4 py-5 text-sm text-slate-600 sm:px-6 lg:px-8">
        Data: Environment Agency open monitoring data. Analysis: independent research.
      </div>
    </footer>
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

export default App;
