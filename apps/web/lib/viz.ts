/**
 * Chart palettes, shared with RLAI SupplyMind so the two products read as one family.
 *
 * Validated per the dataviz skill against each theme's own surface — dark is a separate
 * set of steps, not an inversion of the light one. Assign in fixed order, never cycled;
 * a ninth series folds into "Other" rather than getting a generated hue.
 *
 * The light set carries a contrast WARN on the teal, amber and pink steps, which obliges
 * relief rather than forbidding them: every chart here has visible axis labels and a
 * hover readout, and every module page renders the underlying table beneath the chart,
 * so a value is never carried by the fill alone.
 */

const CATEGORICAL_DARK = [
  "#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767",
];
const CATEGORICAL_LIGHT = [
  "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948",
];

/** Reserved status colours — always paired with an icon or label, never colour alone. */
export const STATUS = {
  good: "#0ca30c",
  warning: "#fab219",
  serious: "#ec835a",
  critical: "#d03b3b",
} as const;

const CHROME_DARK = {
  grid: "#2c2c2a",
  axis: "#383835",
  muted: "#898781",
  textSecondary: "#c3c2b7",
  textPrimary: "#e2e8f0",
  surface: "#0f172a",
};
const CHROME_LIGHT = {
  grid: "#e1e0d9",
  axis: "#c3c2b7",
  muted: "#898781",
  textSecondary: "#52514e",
  textPrimary: "#0b0b0b",
  surface: "#ffffff",
};

export type Theme = "dark" | "light";

export const getCategorical = (theme: Theme) =>
  theme === "dark" ? CATEGORICAL_DARK : CATEGORICAL_LIGHT;

export const getChrome = (theme: Theme) => (theme === "dark" ? CHROME_DARK : CHROME_LIGHT);

export const CATEGORICAL = CATEGORICAL_DARK;
export const CHROME = CHROME_DARK;
