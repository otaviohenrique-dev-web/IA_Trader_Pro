const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const price = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const fmtUsd = (v) => usd.format(Number.isFinite(v) ? v : 0);
export const fmtPrice = (v) => price.format(Number.isFinite(v) ? v : 0);
export const fmtPct = (v, digits = 2) => {
  const n = Number.isFinite(v) ? v : 0;
  return `${n > 0 ? "+" : ""}${n.toFixed(digits)}%`;
};
export const tone = (v) => (v > 0 ? "text-gain" : v < 0 ? "text-loss" : "text-slate-200");
