"use client";

/** Datalist of IANA time zones for site forms; the API validates the value. */
export function TimezoneOptions({ id }: { id: string }) {
  const zones = typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : [];
  return (
    <datalist id={id}>
      {zones.map((zone) => <option key={zone} value={zone} />)}
    </datalist>
  );
}
