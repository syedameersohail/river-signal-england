import { LocateFixed, Search } from "lucide-react";
import { useEffect, useState } from "react";
import type { GeoPoint } from "../types";
import { getCurrentPosition, lookupPostcode } from "../utils/postcode";

interface PostcodeSearchProps {
  disabled?: boolean;
  error: string | null;
  hasActiveSearch: boolean;
  isLoading: boolean;
  onClear: () => void;
  onError: (message: string) => void;
  onLocationFound: (location: GeoPoint, label: string) => void;
}

function useDebouncedValue(value: string, delayMs: number): string {
  const [debouncedValue, setDebouncedValue] = useState(value);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => setDebouncedValue(value), delayMs);
    return () => window.clearTimeout(timeoutId);
  }, [delayMs, value]);

  return debouncedValue;
}

function PostcodeSearch({
  disabled = false,
  error,
  hasActiveSearch,
  isLoading,
  onClear,
  onError,
  onLocationFound,
}: PostcodeSearchProps) {
  const [postcode, setPostcode] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const debouncedPostcode = useDebouncedValue(postcode, 350);
  const hasPostcode = postcode.trim().length > 0;
  const isBusy = isLoading || isSubmitting;

  function clearSearch() {
    setPostcode("");
    onClear();
  }

  async function submitPostcode() {
    setIsSubmitting(true);
    try {
      const lookup = await lookupPostcode(postcode || debouncedPostcode);
      onLocationFound(lookup.location, lookup.postcode);
    } catch (lookupError) {
      onError(lookupError instanceof Error ? lookupError.message : "Postcode lookup failed. Try again.");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function useCurrentLocation() {
    setIsSubmitting(true);
    try {
      const location = await getCurrentPosition();
      onLocationFound(location, "your current location");
    } catch (locationError) {
      onError(locationError instanceof Error ? locationError.message : "Current location could not be used.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <form
      className="rounded-lg border border-slate-200 bg-white p-4"
      onSubmit={(event) => {
        event.preventDefault();
        void submitPostcode();
      }}
    >
      <label className="block text-sm font-semibold text-ink" htmlFor="postcode-search">
        Enter your postcode
      </label>
      <div className="mt-2 grid gap-2 sm:grid-cols-[1fr_auto]">
        <div className="flex min-w-0 items-center rounded-md border border-slate-300 bg-white px-3 focus-within:border-riverblue focus-within:ring-2 focus-within:ring-riverblue/20">
          <Search aria-hidden="true" className="h-4 w-4 shrink-0 text-slate-500" />
          <input
            autoComplete="postal-code"
            className="min-w-0 flex-1 bg-transparent px-2 py-2 text-sm uppercase outline-none"
            disabled={disabled || isBusy}
            id="postcode-search"
            onChange={(event) => {
              setPostcode(event.target.value);
              if (!event.target.value && hasActiveSearch) {
                onClear();
              }
            }}
            placeholder="OX1 2JD"
            type="search"
            value={postcode}
          />
          {(hasPostcode || hasActiveSearch) && !isBusy ? (
            <button
              aria-label="Clear postcode search"
              className="ml-1 rounded-md border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-600 hover:border-riverblue hover:text-riverblue"
              onClick={clearSearch}
              type="button"
            >
              Clear
            </button>
          ) : null}
        </div>
        <button
          className="inline-flex items-center justify-center gap-2 rounded-md border border-riverblue bg-riverblue px-3 py-2 text-sm font-semibold text-white transition hover:bg-riverblue-dark disabled:cursor-not-allowed disabled:opacity-50"
          disabled={disabled || isBusy || !hasPostcode}
          type="submit"
        >
          <Search aria-hidden="true" className="h-4 w-4" />
          Search
        </button>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <button
          className="inline-flex items-center gap-2 rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 transition hover:border-riverblue hover:text-riverblue disabled:cursor-not-allowed disabled:opacity-50"
          disabled={disabled || isBusy}
          onClick={() => void useCurrentLocation()}
          type="button"
        >
          <LocateFixed aria-hidden="true" className="h-4 w-4" />
          Use my current location
        </button>
        <button
          className="rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 transition hover:border-riverblue hover:text-riverblue disabled:cursor-not-allowed disabled:opacity-50"
          disabled={disabled || isBusy}
          onClick={clearSearch}
          type="button"
        >
          Show national feed
        </button>
      </div>

      {isBusy ? <p className="mt-3 text-sm text-slatecopy">Finding monitored rivers nearby...</p> : null}
      {error ? <p className="mt-3 text-sm font-semibold text-red-800">{error}</p> : null}
    </form>
  );
}

export default PostcodeSearch;
