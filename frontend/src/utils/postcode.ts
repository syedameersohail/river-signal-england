import type { GeoPoint, PostcodeLookupResult, PostcodesIoResponse } from "../types";

const postcodeCache: Record<string, PostcodeLookupResult> = {};

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
