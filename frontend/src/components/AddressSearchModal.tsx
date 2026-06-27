import { Loader2, MapPin, Search, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { AddressSuggestion, GeoPoint } from "../types";
import { searchAddresses } from "../utils/postcode";

interface AddressSearchModalProps {
  onClose: () => void;
  onSelect: (location: GeoPoint, label: string) => void;
}

function AddressSearchModal({ onClose, onSelect }: AddressSearchModalProps) {
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState<AddressSuggestion[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeIndex, setActiveIndex] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    function handleEscape(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
  }, [onClose]);

  const fetchSuggestions = useCallback(async (text: string) => {
    if (text.trim().length < 2) {
      setSuggestions([]);
      setError(null);
      setIsLoading(false);
      return;
    }

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setIsLoading(true);
    setError(null);

    try {
      const results = await searchAddresses(text, controller.signal);
      if (!controller.signal.aborted) {
        setSuggestions(results);
        setActiveIndex(-1);
        if (results.length === 0) {
          setError("No addresses found. Try a different search term.");
        }
      }
    } catch (err) {
      if (!controller.signal.aborted) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setError("Search failed. Try again.");
        setSuggestions([]);
      }
    } finally {
      if (!controller.signal.aborted) {
        setIsLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      void fetchSuggestions(query);
    }, 300);
    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [query, fetchSuggestions]);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  function handleSelect(suggestion: AddressSuggestion) {
    const label = suggestion.postcode
      ? suggestion.postcode
      : suggestion.displayName.split(",")[0];
    onSelect(suggestion.location, label);
    onClose();
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (suggestions.length === 0) return;

    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => (i < suggestions.length - 1 ? i + 1 : 0));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => (i > 0 ? i - 1 : suggestions.length - 1));
    } else if (e.key === "Enter" && activeIndex >= 0) {
      e.preventDefault();
      handleSelect(suggestions[activeIndex]);
    }
  }

  useEffect(() => {
    if (activeIndex >= 0 && listRef.current) {
      const item = listRef.current.children[activeIndex] as HTMLElement | undefined;
      item?.scrollIntoView({ block: "nearest" });
    }
  }, [activeIndex]);

  function highlightMatch(text: string) {
    if (!query.trim()) return text;
    const escaped = query.trim().replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const regex = new RegExp(`(${escaped})`, "gi");
    const parts = text.split(regex);
    return parts.map((part, i) =>
      regex.test(part) ? (
        <strong key={i} className="font-bold text-slate-900">{part}</strong>
      ) : (
        <span key={i}>{part}</span>
      ),
    );
  }

  function formatSuggestion(s: AddressSuggestion): string {
    const parts = s.displayName.split(",").map((p) => p.trim());
    if (parts.length > 4) {
      return [parts[0], parts[1], parts[parts.length - 3], s.postcode || parts[parts.length - 2]]
        .filter(Boolean)
        .join(", ");
    }
    return s.displayName;
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 pt-[10vh] transition-opacity duration-200"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      role="dialog"
      aria-modal="true"
      aria-label="Find an address"
    >
      <div className="mx-4 w-full max-w-[600px] rounded-lg bg-white p-6 shadow-xl">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-2xl font-bold text-slate-900">Find an address</h2>
            <p className="mt-2 text-sm text-slate-600">
              Type a part of address or postcode to begin
            </p>
          </div>
          <button
            className="rounded-md p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
            onClick={onClose}
            type="button"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="relative mt-4">
          <div className="flex items-center rounded-lg border-2 border-slate-300 bg-white px-4 transition-colors focus-within:border-teal-500 focus-within:ring-2 focus-within:ring-teal-500/20">
            <Search className="h-5 w-5 shrink-0 text-slate-400" />
            <input
              ref={inputRef}
              className="min-h-[44px] w-full bg-transparent px-3 text-base outline-none placeholder:text-slate-400"
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="E.g. 'SW1A 1AA' or '36 Factory Lane'"
              type="text"
              value={query}
              aria-autocomplete="list"
              aria-controls="address-suggestions"
              aria-expanded={suggestions.length > 0}
              role="combobox"
            />
            {isLoading ? (
              <Loader2 className="h-5 w-5 shrink-0 animate-spin text-teal-600" />
            ) : null}
          </div>

          {suggestions.length > 0 ? (
            <ul
              ref={listRef}
              id="address-suggestions"
              className="mt-1 max-h-96 overflow-y-auto rounded-lg border border-slate-200 bg-white shadow-lg"
              role="listbox"
            >
              {suggestions.map((suggestion, index) => (
                <li
                  key={`${suggestion.location.lat}-${suggestion.location.lon}-${index}`}
                  className={`flex cursor-pointer items-start gap-3 border-b border-slate-100 p-3 transition last:border-b-0 ${
                    index === activeIndex
                      ? "bg-teal-50"
                      : "hover:bg-slate-50"
                  }`}
                  onClick={() => handleSelect(suggestion)}
                  onMouseEnter={() => setActiveIndex(index)}
                  role="option"
                  aria-selected={index === activeIndex}
                >
                  <MapPin className="mt-0.5 h-4 w-4 shrink-0 text-teal-600" />
                  <span className="text-sm text-slate-700">
                    {highlightMatch(formatSuggestion(suggestion))}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}

          {error && !isLoading && query.trim().length >= 2 ? (
            <p className="mt-3 text-center text-sm text-slate-500">{error}</p>
          ) : null}

          {!isLoading && !error && query.trim().length >= 2 && suggestions.length === 0 ? null : null}

          {isLoading && suggestions.length === 0 ? (
            <p className="mt-3 text-center text-sm text-slate-500">Searching...</p>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export default AddressSearchModal;
