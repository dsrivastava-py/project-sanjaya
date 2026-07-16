// §4.3 categorical palette — VALIDATED (dataviz validator: all checks pass;
// worst adjacent CVD ΔE 16.3 dark / 18.6 light). Do not alter without re-running.
// Color follows the category ENTITY via its color_slot — never its rank.
import type { Category } from "./api";

export type ThemeName = "dark" | "light";

const SLOTS: Record<ThemeName, string[]> = {
  dark: ["#B9801A", "#3E8BE3", "#D65A7C", "#1DA595", "#DB6B33", "#8578E8", "#5EA742", "#B368DC"],
  light: ["#A66F0E", "#2A78D6", "#C43A61", "#0A9182", "#C24F16", "#6E5FD6", "#3F8A24", "#9747C9"],
};

// Idle/locked: never a colored category, no legend slot (§4.3).
export const IDLE: Record<ThemeName, string> = { dark: "#2A3149", light: "#D9D8CF" };

// "Other"/uncategorized: neutral --text-3 (§4.3).
export const NEUTRAL: Record<ThemeName, string> = { dark: "#6E7691", light: "#7C829B" };

// Status colors — fixed, reserved, never used for series; always icon + label (§4.3).
export const STATUS = {
  good: "#22A06B",
  warning: "#E2A63D",
  serious: "#E07A3F",
  critical: "#D14D4D",
} as const;

// Sequential gold ramp for the calendar heatmap (one hue, light→dark by
// intensity). Dark-mode steps verified ≥2:1 vs surface #121828
// (2.53 / 3.97 / 6.27 / 9.32); zero-activity cells render surface + hairline.
export const HEAT_RAMP: Record<ThemeName, string[]> = {
  dark: ["#6E5619", "#93731D", "#BD9430", "#E8B44A"],
  light: ["#F0DFB6", "#DDBE77", "#C29A3F", "#A66F0E"],
};

export function slotColor(slot: number | null | undefined, theme: ThemeName): string {
  if (!slot || slot < 1 || slot > 8) return NEUTRAL[theme];
  return SLOTS[theme][slot - 1];
}

export function catColor(cat: Category | undefined, theme: ThemeName): string {
  return slotColor(cat?.color_slot, theme);
}

/** Resolve a category-totals key ("3" | "uncategorized") to color + name. */
export function keyColorName(
  key: string,
  cats: Category[] | undefined,
  theme: ThemeName,
): { color: string; name: string } {
  if (key === "uncategorized") return { color: NEUTRAL[theme], name: "Uncategorized" };
  const cat = cats?.find((c) => c.id === Number(key));
  return { color: catColor(cat, theme), name: cat?.name ?? `#${key}` };
}
