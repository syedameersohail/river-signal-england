import { Map as MapIcon } from "lucide-react";
import maplibregl, { type LngLatBoundsLike, type Map as MapLibreMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  getSeverity,
  getSeverityHex,
  titleCaseSiteName,
  topDriver,
} from "../lib/feed";
import type { LocalSiteEntry, SeverityBand, SiteEntry } from "../types";

type MapMode = "all" | "flagged";

interface MapViewProps {
  error: string | null;
  isLoading: boolean;
  onOpenSite: (site: SiteEntry) => void;
  regions: string[];
  sites: SiteEntry[];
}

function MapView({ error, isLoading, onOpenSite, regions, sites }: MapViewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);
  const sitesRef = useRef<SiteEntry[]>(sites);
  const visibleSitesRef = useRef<SiteEntry[]>(sites);
  const [mapMode, setMapMode] = useState<MapMode>("all");
  const [region, setRegion] = useState("");

  const visibleSites = useMemo(
    () => (mapMode === "flagged" ? sites.filter((site) => site.is_flagged) : sites),
    [mapMode, sites],
  );

  useEffect(() => {
    sitesRef.current = sites;
  }, [sites]);

  useEffect(() => {
    visibleSitesRef.current = visibleSites;
  }, [visibleSites]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) {
      return;
    }

    const map = new maplibregl.Map({
      container: containerRef.current,
      center: [-1.8, 52.8],
      zoom: 5.35,
      attributionControl: false,
      style: baseMapStyle(),
    });

    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");
    popupRef.current = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 12 });
    mapRef.current = map;

    map.on("load", () => {
      map.addSource("sites", {
        type: "geojson",
        data: buildSiteGeoJson(visibleSitesRef.current),
      });

      map.addLayer({
        id: "site-circles",
        type: "circle",
        source: "sites",
        paint: {
          "circle-color": ["get", "color"],
          "circle-radius": ["case", ["get", "flagged"], 6, 3],
          "circle-opacity": 0.82,
          "circle-stroke-color": ["case", ["get", "flagged"], "#111827", "#ffffff"],
          "circle-stroke-width": ["case", ["get", "flagged"], 1.4, 0.6],
        },
      });

      map.on("mouseenter", "site-circles", (event) => {
        map.getCanvas().style.cursor = "pointer";
        const feature = event.features?.[0];
        const coordinates = feature?.geometry.type === "Point" ? feature.geometry.coordinates : null;
        if (!feature || !coordinates) {
          return;
        }

        popupRef.current
          ?.setLngLat(coordinates as [number, number])
          .setHTML(
            `<div class="map-tooltip"><strong>${escapeHtml(String(feature.properties?.name ?? ""))}</strong><span>Rank #${escapeHtml(
              String(feature.properties?.rank ?? ""),
            )} - ${escapeHtml(String(feature.properties?.severity ?? ""))}</span><span>${escapeHtml(
              String(feature.properties?.driver ?? ""),
            )}</span></div>`,
          )
          .addTo(map);
      });

      map.on("mouseleave", "site-circles", () => {
        map.getCanvas().style.cursor = "";
        popupRef.current?.remove();
      });

      map.on("click", "site-circles", (event) => {
        const siteId = String(event.features?.[0]?.properties?.siteId ?? "");
        const site = sitesRef.current.find((item) => item.site_id === siteId);
        if (site) {
          onOpenSite(site);
        }
      });
    });

    return () => {
      popupRef.current?.remove();
      map.remove();
      mapRef.current = null;
    };
  }, [onOpenSite]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getSource("sites")) {
      return;
    }

    const source = map.getSource("sites") as maplibregl.GeoJSONSource;
    source.setData(buildSiteGeoJson(visibleSites));
    if (visibleSites.length > 0 && visibleSites.length <= 10) {
      fitMapToSites(map, visibleSites, 56, 11);
    }
  }, [visibleSites]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !region) {
      return;
    }

    const bounds = boundsForSites(sites.filter((site) => site.region === region));
    if (bounds) {
      map.fitBounds(bounds, { padding: 46, duration: prefersReducedMotion() ? 0 : 650, maxZoom: 9 });
    }
  }, [region, sites]);

  return (
    <section className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8" aria-label="River site map">
      {error ? <Notice tone="error">{error}</Notice> : null}
      {isLoading ? <Notice>Loading the map data...</Notice> : null}

      <div className="relative rounded-lg border border-slate-200 bg-white p-3">
        <aside className="mb-3 rounded-lg border border-slate-200 bg-white/95 p-4 shadow-lg backdrop-blur-sm lg:absolute lg:left-4 lg:top-4 lg:z-10 lg:mb-0 lg:w-80">
          <h2 className="text-lg font-semibold text-ink">Map view</h2>
          <p className="mt-2 text-sm leading-6 text-slatecopy">
            Spatial context for the ranked feed. Points are coloured by severity and larger points
            are above the flag threshold.
          </p>

          <fieldset className="mt-5">
            <legend className="text-sm font-semibold text-ink">Sites shown</legend>
            <div className="mt-2 grid grid-cols-2 overflow-hidden rounded-md border border-slate-300">
              {(["all", "flagged"] as MapMode[]).map((mode) => (
                <button
                  aria-pressed={mapMode === mode}
                  className={`px-3 py-2 text-sm font-semibold ${
                    mapMode === mode ? "bg-riverblue text-white" : "bg-white text-slate-700"
                  }`}
                  key={mode}
                  onClick={() => setMapMode(mode)}
                  type="button"
                >
                  {mode === "all" ? "All sites" : "Flagged only"}
                </button>
              ))}
            </div>
          </fieldset>

          <Select label="Zoom to region" onChange={setRegion} options={regions} value={region} />

          <div className="mt-5 space-y-2 text-sm text-slate-700">
            <p>
              <span className="font-semibold text-slate-900">{visibleSites.length.toLocaleString("en-GB")}</span>{" "}
              sites currently plotted.
            </p>
            <SeverityLegend />
          </div>
        </aside>

        <div
          className="h-[560px] min-h-[420px] rounded-lg border border-slate-300"
          ref={containerRef}
          role="img"
          aria-label="Map of river chemistry monitoring sites in England"
        />
      </div>
    </section>
  );
}

export function LocalMapPreview({
  onViewMap,
  sites,
}: {
  onViewMap: () => void;
  sites: LocalSiteEntry[];
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) {
      return;
    }

    const map = new maplibregl.Map({
      container: containerRef.current,
      center: [-1.8, 52.8],
      zoom: 5,
      attributionControl: false,
      interactive: false,
      style: baseMapStyle(),
    });

    mapRef.current = map;
    map.on("load", () => {
      map.addSource("local-sites", {
        type: "geojson",
        data: buildSiteGeoJson(sites),
      });

      map.addLayer({
        id: "local-site-circles",
        type: "circle",
        source: "local-sites",
        paint: {
          "circle-color": ["get", "color"],
          "circle-radius": 5,
          "circle-opacity": 0.85,
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 1,
        },
      });

      fitMapToSites(map, sites, 28, 10);
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getSource("local-sites")) {
      return;
    }

    const source = map.getSource("local-sites") as maplibregl.GeoJSONSource;
    source.setData(buildSiteGeoJson(sites));
    fitMapToSites(map, sites, 28, 10);
  }, [sites]);

  return (
    <div className="space-y-2">
      <div
        aria-label="Map preview of local river monitoring sites"
        className="h-36 rounded-lg border border-slate-300"
        ref={containerRef}
        role="img"
      />
      <button
        className="inline-flex w-full items-center justify-center gap-2 rounded-md border border-riverblue bg-riverblue px-3 py-2 text-sm font-semibold text-white transition hover:bg-riverblue-dark"
        onClick={onViewMap}
        type="button"
      >
        View on full map
        <MapIcon aria-hidden="true" className="h-4 w-4" />
      </button>
    </div>
  );
}

function baseMapStyle(): maplibregl.StyleSpecification {
  return {
    version: 8,
    sources: {
      osm: {
        type: "raster",
        tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
        tileSize: 256,
        attribution: "OpenStreetMap contributors",
      },
    },
    layers: [
      {
        id: "osm",
        type: "raster",
        source: "osm",
      },
    ],
  };
}

function buildSiteGeoJson(sites: SiteEntry[]) {
  return {
    type: "FeatureCollection" as const,
    features: sites
      .filter((site) => Number.isFinite(site.lon) && Number.isFinite(site.lat))
      .map((site) => {
        const severity = getSeverity(site.anomaly_score);
        return {
          type: "Feature" as const,
          geometry: {
            type: "Point" as const,
            coordinates: [site.lon, site.lat],
          },
          properties: {
            siteId: site.site_id,
            name: titleCaseSiteName(site.site_label),
            rank: site.anomaly_rank,
            severity,
            driver: topDriver(site),
            flagged: site.is_flagged,
            color: getSeverityHex(severity),
          },
        };
      }),
  };
}

function boundsForSites(sites: SiteEntry[]): LngLatBoundsLike | null {
  const locatedSites = sites.filter((site) => Number.isFinite(site.lon) && Number.isFinite(site.lat));
  if (locatedSites.length === 0) {
    return null;
  }

  const bounds = new maplibregl.LngLatBounds(
    [locatedSites[0].lon, locatedSites[0].lat],
    [locatedSites[0].lon, locatedSites[0].lat],
  );

  locatedSites.forEach((site) => bounds.extend([site.lon, site.lat]));
  return bounds;
}

function fitMapToSites(map: MapLibreMap, sites: SiteEntry[], padding: number, maxZoom: number) {
  const bounds = boundsForSites(sites);
  if (!bounds) {
    return;
  }

  map.fitBounds(bounds, {
    padding,
    duration: prefersReducedMotion() ? 0 : 450,
    maxZoom,
  });
}

function SeverityLegend() {
  return (
    <div className="grid grid-cols-2 gap-2">
      {(["Extreme", "High", "Moderate", "Lower"] as SeverityBand[]).map((severity) => (
        <span className="inline-flex items-center gap-2" key={severity}>
          <span className={`h-3 w-3 rounded-sm border border-slate-700/30 ${severitySwatchClass(severity)}`} />
          {severity}
        </span>
      ))}
    </div>
  );
}

function severitySwatchClass(severity: SeverityBand): string {
  return {
    Extreme: "bg-red-800",
    High: "bg-red-600",
    Moderate: "bg-amber-500",
    Lower: "bg-emerald-600",
  }[severity];
}

function Select({
  label,
  onChange,
  options,
  value,
}: {
  label: string;
  onChange: (value: string) => void;
  options: string[];
  value: string;
}) {
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

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (character) => {
    const entities: Record<string, string> = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;",
    };
    return entities[character];
  });
}

function prefersReducedMotion(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export default MapView;
