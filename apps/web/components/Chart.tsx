"use client";

/**
 * Charts for ShopperMind.
 *
 * Hand-rolled SVG rather than a chart library, and theme-aware: the dark and light
 * categorical palettes are separate validated sets from `lib/viz`, shared with RLAI
 * SupplyMind. Dark is not an inversion of light — it is its own set of steps, checked
 * against the dark surface.
 *
 * Rules held here: one axis, never two. Hues assigned in fixed order and never cycled.
 * Recessive gridlines. Direct labels selectively, never on every point. A hover layer on
 * every plot.
 */

import { useId, useState } from "react";

import { useTheme } from "@/lib/theme";
import { getCategorical, getChrome } from "@/lib/viz";

export type Point = { label: string; value: number | null };

function niceMax(value: number): number {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const scaled = value / magnitude;
  const step = scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 5 ? 5 : 10;
  return step * magnitude;
}

function compact(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1e7) return `${(value / 1e7).toFixed(1)}Cr`;
  if (abs >= 1e5) return `${(value / 1e5).toFixed(1)}L`;
  if (abs >= 1000) return `${(value / 1000).toFixed(1)}k`;
  if (abs >= 100) return value.toFixed(0);
  return value.toFixed(abs < 10 ? 1 : 0);
}

type ChartProps = {
  title: string;
  points: Point[];
  unit?: string;
  kind?: "bar" | "line";
  source?: string;
  height?: number;
  colorIndex?: number;
};

export function Chart({
  title, points, unit = "", kind = "bar", source, height = 190, colorIndex = 0,
}: ChartProps) {
  const id = useId();
  const { theme } = useTheme();
  const [hover, setHover] = useState<number | null>(null);

  const palette = getCategorical(theme);
  const chrome = getChrome(theme);

  const clean = points.filter((p) => p.value !== null && !Number.isNaN(p.value));
  if (clean.length === 0) {
    return (
      <figure className="chart">
        <figcaption className="chart__title">{title}</figcaption>
        <p className="hint">No data for this period.</p>
      </figure>
    );
  }

  const values = clean.map((p) => p.value as number);
  const hasNegative = values.some((v) => v < 0);
  const top = niceMax(Math.max(...values, 0));
  const bottom = hasNegative ? -niceMax(Math.abs(Math.min(...values))) : 0;
  const span = top - bottom || 1;

  const W = 720;
  const H = height;
  const padL = 46;
  const padR = 14;
  const padT = 18;
  const padB = 34;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;

  const y = (v: number) => padT + plotH - ((v - bottom) / span) * plotH;
  const zeroY = y(0);

  // Four gridlines is enough to read a value against; more competes with the marks.
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => bottom + span * t);
  const colour = palette[colorIndex % palette.length];

  // Thin the axis labels by how wide they actually are, not by how many there are.
  // Ten short labels fit where six long ones collide, and colliding labels are worse
  // than absent ones — the hover readout names every point anyway.
  const slotW = plotW / clean.length;
  const longest = Math.max(...clean.map((p) => Math.min(p.label.length, 14)));
  const APPROX_CHAR_PX = 5.4;   // at the 10px label size
  const labelEvery = Math.max(1, Math.ceil((longest * APPROX_CHAR_PX + 8) / slotW));
  // Truncate to what the slot can hold once thinning is accounted for.
  const maxChars = Math.max(4, Math.floor((slotW * labelEvery - 6) / APPROX_CHAR_PX));

  return (
    <figure className="chart">
      <figcaption className="chart__title">{title}</figcaption>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`${title}${unit ? ` in ${unit}` : ""}`}
        onMouseLeave={() => setHover(null)}
      >
        {ticks.map((t, i) => (
          <g key={i}>
            <line
              x1={padL} x2={W - padR} y1={y(t)} y2={y(t)}
              stroke={chrome.grid} strokeWidth={1}
            />
            <text
              x={padL - 8} y={y(t) + 4} textAnchor="end"
              fontSize={10} fill={chrome.muted} fontFamily="var(--mono)"
            >
              {compact(t)}
            </text>
          </g>
        ))}
        {hasNegative && (
          <line x1={padL} x2={W - padR} y1={zeroY} y2={zeroY}
                stroke={chrome.axis} strokeWidth={1} />
        )}

        {kind === "bar" ? (
          clean.map((p, i) => {
            // A 2px surface gap between adjacent fills, per the mark spec.
            const barW = Math.max(slotW - 4, 2);
            const x = padL + i * slotW + 2;
            const v = p.value as number;
            const yTop = v >= 0 ? y(v) : zeroY;
            const h = Math.max(Math.abs(y(v) - zeroY), 1);
            return (
              <g key={`${p.label}-${i}`}>
                <rect
                  x={x} y={yTop} width={barW} height={h}
                  fill={v < 0 ? "var(--critical)" : colour}
                  rx={4}
                  opacity={hover === null || hover === i ? 1 : 0.42}
                />
                {/* Hit target spans the full slot height, not just the mark. */}
                <rect
                  x={padL + i * slotW} y={padT} width={slotW} height={plotH}
                  fill="transparent"
                  onMouseEnter={() => setHover(i)}
                />
              </g>
            );
          })
        ) : (
          <>
            <polyline
              points={clean
                .map((p, i) => {
                  const x = padL + (plotW / Math.max(clean.length - 1, 1)) * i;
                  return `${x},${y(p.value as number)}`;
                })
                .join(" ")}
              fill="none" stroke={colour} strokeWidth={2}
              strokeLinejoin="round" strokeLinecap="round"
            />
            {clean.map((p, i) => {
              const x = padL + (plotW / Math.max(clean.length - 1, 1)) * i;
              return (
                <g key={`${p.label}-${i}`}>
                  {hover === i && (
                    <>
                      <line x1={x} x2={x} y1={padT} y2={padT + plotH}
                            stroke={chrome.axis} strokeWidth={1} />
                      <circle
                        cx={x} cy={y(p.value as number)} r={5} fill={colour}
                        stroke={chrome.surface} strokeWidth={2}
                      />
                    </>
                  )}
                  <rect
                    x={x - plotW / clean.length / 2} y={padT}
                    width={plotW / clean.length} height={plotH}
                    fill="transparent" onMouseEnter={() => setHover(i)}
                  />
                </g>
              );
            })}
          </>
        )}

        {clean.map((p, i) => {
          if (i % labelEvery !== 0) return null;
          const x = kind === "bar"
            ? padL + i * slotW + slotW / 2
            : padL + (plotW / Math.max(clean.length - 1, 1)) * i;
          const short =
            p.label.length > maxChars ? `${p.label.slice(0, maxChars - 1)}…` : p.label;
          return (
            <text
              key={`l-${i}`} x={x} y={H - 12} textAnchor="middle"
              fontSize={10} fill={chrome.muted}
            >
              {short}
            </text>
          );
        })}

        {hover !== null && clean[hover] && (
          <g pointerEvents="none">
            <text
              x={padL} y={padT - 5} fontSize={11} fill={chrome.textPrimary}
              fontFamily="var(--mono)" fontWeight={600}
            >
              {clean[hover].label}: {compact(clean[hover].value as number)}
              {unit && unit !== "INR" ? ` ${unit}` : ""}
            </text>
          </g>
        )}
      </svg>
      <p className="u-eyebrow u-eyebrow--muted chart__source" id={id}>
        {source ?? `Source: ShopperMind${unit ? ` · ${unit}` : ""}`}
      </p>
    </figure>
  );
}
