"use client";

/** Filters sit in one row above the content they filter. */
export function PeriodPicker({
  value, onChange, options = [7, 14, 30, 90],
}: {
  value: number;
  onChange: (days: number) => void;
  options?: number[];
}) {
  return (
    <div className="filters">
      <span className="u-eyebrow u-eyebrow--muted">Period</span>
      {options.map((d) => (
        <button
          key={d}
          className="btn btn--ghost btn--sm"
          aria-pressed={value === d}
          onClick={() => onChange(d)}
        >
          {d === 7 ? "7 days" : d === 14 ? "14 days" : d === 30 ? "30 days" : `${d} days`}
        </button>
      ))}
    </div>
  );
}
