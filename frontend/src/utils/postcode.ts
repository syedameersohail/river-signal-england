import type { AddressSuggestion, GeoPoint, PostcodeLookupResult, PostcodesIoResponse } from "../types";

const postcodeCache: Record<string, PostcodeLookupResult> = {};
const autocompleteCache: Record<string, AddressSuggestion[]> = {};

export function normalisePostcode(value: string): string {
  return value.trim().replace(/\s+/g, "").toUpperCase();
}

export async function lookupPostcode(postcode: string): Promise<PostcodeLookupResult> {
  const normalised = normalisePostcode(postcode);

  if (!normalised) {
    throw new Error("Enter a postcode to search nearby rivers.");
  }

  if (postcodeCache[normalised]) {
    return postcodeCache[normalised];
  }

  let response: Response;
  try {
    response = await fetch(`https://api.postcodes.io/postcodes/${encodeURIComponent(normalised)}`);
  } catch {
    throw new Error("Postcode lookup is unavailable right now. Try again in a moment.");
  }

  if (response.status === 404) {
    throw new Error("That postcode was not recognised. Check it and try again.");
  }

  if (!response.ok) {
    throw new Error("Postcode lookup is unavailable right now. Try again in a moment.");
  }

  const payload = (await response.json()) as PostcodesIoResponse;

  if (payload.status !== 200 || !payload.result) {
    throw new Error("That postcode was not recognised. Check it and try again.");
  }

  const result = {
    postcode: payload.result.postcode,
    location: {
      lat: payload.result.latitude,
      lon: payload.result.longitude,
    },
  };

  postcodeCache[normalised] = result;
  return result;
}

interface NominatimResult {
  display_name: string;
  lat: string;
  lon: string;
}

interface PostcodesIoAutocompleteResponse {
  status: number;
  result: string[] | null;
}

export async function searchAddresses(
  query: string,
  signal?: AbortSignal,
): Promise<AddressSuggestion[]> {
  const trimmed = query.trim();
  if (trimmed.length < 2) return [];

  if (autocompleteCache[trimmed]) {
    return autocompleteCache[trimmed];
  }

  const looksLikePostcode = /^[A-Z]{1,2}\d/i.test(trimmed);

  if (looksLikePostcode) {
    try {
      const results = await searchPostcodesIo(trimmed, signal);
      if (results.length > 0) {
        autocompleteCache[trimmed] = results;
        return results;
      }
    } catch {
      // fall through to Nominatim
    }
  }

  const results = await searchNominatim(trimmed, signal);
  autocompleteCache[trimmed] = results;
  return results;
}

async function searchPostcodesIo(
  partial: string,
  signal?: AbortSignal,
): Promise<AddressSuggestion[]> {
  const normalised = normalisePostcode(partial);
  const response = await fetch(
    `https://api.postcodes.io/postcodes/${encodeURIComponent(normalised)}/autocomplete`,
    { signal },
  );

  if (!response.ok) return [];

  const payload = (await response.json()) as PostcodesIoAutocompleteResponse;
  if (payload.status !== 200 || !payload.result?.length) return [];

  const lookups = await Promise.all(
    payload.result.slice(0, 8).map(async (pc) => {
      try {
        const result = await lookupPostcode(pc);
        return {
          displayName: result.postcode,
          postcode: result.postcode,
          location: result.location,
        } satisfies AddressSuggestion;
      } catch {
        return null;
      }
    }),
  );

  return lookups.filter((r): r is AddressSuggestion => r !== null);
}

async function searchNominatim(
  query: string,
  signal?: AbortSignal,
): Promise<AddressSuggestion[]> {
  const params = new URLSearchParams({
    q: query,
    countrycodes: "gb",
    format: "json",
    addressdetails: "1",
    limit: "8",
  });

  const response = await fetch(
    `https://nominatim.openstreetmap.org/search?${params.toString()}`,
    {
      signal,
      headers: { "Accept-Language": "en" },
    },
  );

  if (!response.ok) return [];

  const results = (await response.json()) as NominatimResult[];

  return results.map((r) => {
    const postcode = extractPostcode(r.display_name);
    return {
      displayName: r.display_name,
      postcode,
      location: { lat: parseFloat(r.lat), lon: parseFloat(r.lon) },
    };
  });
}

function extractPostcode(displayName: string): string {
  const match = displayName.match(/[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}/i);
  return match ? match[0].toUpperCase() : "";
}

export function getCurrentPosition(): Promise<GeoPoint> {
  if (!navigator.geolocation) {
    return Promise.reject(new Error("Your browser does not support current location lookup."));
  }

  return new Promise((resolve, reject) => {
    navigator.geolocation.getCurrentPosition(
      (position) => {
        resolve({
          lat: position.coords.latitude,
          lon: position.coords.longitude,
        });
      },
      () => reject(new Error("Current location could not be used. Check browser permissions and try again.")),
      { enableHighAccuracy: false, maximumAge: 300000, timeout: 10000 },
    );
  });
}
