import type { GeoPoint, LocalSiteEntry, SiteEntry } from "../types";

const EARTH_RADIUS_KM = 6371;

function toRadians(value: number): number {
  return (value * Math.PI) / 180;
}

export function haversineDistanceKm(from: GeoPoint, to: GeoPoint): number {
  const latitudeDelta = toRadians(to.lat - from.lat);
  const longitudeDelta = toRadians(to.lon - from.lon);
  const fromLatitude = toRadians(from.lat);
  const toLatitude = toRadians(to.lat);

  const haversine =
    Math.sin(latitudeDelta / 2) ** 2 +
    Math.cos(fromLatitude) * Math.cos(toLatitude) * Math.sin(longitudeDelta / 2) ** 2;

  return 2 * EARTH_RADIUS_KM * Math.asin(Math.sqrt(haversine));
}

export function nearestSites(
  sites: SiteEntry[],
  origin: GeoPoint,
  limit = 10,
  maxDistanceKm = 50,
): LocalSiteEntry[] {
  return sites
    .filter((site) => Number.isFinite(site.lat) && Number.isFinite(site.lon))
    .map((site) => ({
      ...site,
      distanceKm: haversineDistanceKm(origin, { lat: site.lat, lon: site.lon }),
    }))
    .filter((site) => site.distanceKm <= maxDistanceKm)
    .sort((left, right) => left.distanceKm - right.distanceKm)
    .slice(0, limit);
}

export function formatDistanceKm(value: number): string {
  if (value < 1) {
    return `${Math.round(value * 1000).toLocaleString("en-GB")} m away`;
  }

  return `${value.toFixed(1)} km away`;
}
