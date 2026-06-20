export type DriverDirection = "high" | "low";

export interface Driver {
  name: string;
  label?: string;
  z: number;
  direction: DriverDirection;
  description: string;
  unit?: string;
}

export interface SiteEntry {
  site_id: string;
  site_label: string;
  display_name?: string;
  lat: number;
  lon: number;
  region?: string;
  area?: string;
  sub_area?: string;
  anomaly_rank: number;
  anomaly_score: number;
  is_flagged: boolean;
  flag_threshold?: number;
  score_reference?: string;
  score_peer_group_size?: number;
  total_observations?: number | null;
  first_sample?: string | null;
  last_sample?: string | null;
  distinct_sample_dates?: number | null;
  avg_days_between_visits?: number | null;
  confidence_tier?: "well" | "moderate" | "limited";
  drivers?: Driver[];
  summary?: string;
  wfd_type?: string;
  wfd_type_resolved?: string | null;
  wfd_type_inferred: boolean;
  water_body_id?: string;
  water_body_name?: string;
  peer_agreement_ratio: number | null;
  dominant_peer_type: string | null;
  is_cross_type: boolean;
  is_strong_agreement: boolean;
  peer_site_ids: string[];
}

export interface LocalSiteEntry extends SiteEntry {
  distanceKm: number;
}

export interface RankedFeed {
  generated_at: string;
  data_period_start?: string | null;
  data_period_end?: string | null;
  total_sites: number;
  flagged_sites: number;
  top_n_with_narratives: number;
  scoring_method: string;
  feature_cols?: string[];
  panel?: Record<string, string>;
  feed: SiteEntry[];
}

export interface Site extends SiteEntry {}
export interface FeedData extends RankedFeed {}

export type SeverityBand = "Extreme" | "High" | "Moderate" | "Lower";

export interface Filters {
  region: string;
  severity: string;
  driver: string;
  query: string;
}

export interface GeoPoint {
  lat: number;
  lon: number;
}

export interface PostcodesIoResult {
  postcode: string;
  latitude: number;
  longitude: number;
}

export interface PostcodesIoResponse {
  status: number;
  result: PostcodesIoResult | null;
}

export interface PostcodeLookupResult {
  postcode: string;
  location: GeoPoint;
}

export type LocalSearchStatus = "idle" | "loading" | "ready" | "error";

export interface LocalSearchState {
  error: string | null;
  label: string;
  location: GeoPoint | null;
  results: LocalSiteEntry[];
  status: LocalSearchStatus;
}
