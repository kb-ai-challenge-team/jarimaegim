/** Quantile knots used for inverse-transform sampling. Restricting to P10-P90 keeps tail outliers out of the result. */
export const QUANTILE_KNOTS = [0.1, 0.25, 0.5, 0.75, 0.9];

/** Linear-interpolated p-quantile of an already-sorted numeric array. */
export function quantile(sorted, p) {
  if (sorted.length === 0) throw new Error("quantile requires at least one value");
  if (p <= 0) return sorted[0];
  if (p >= 1) return sorted[sorted.length - 1];
  const position = (sorted.length - 1) * p;
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  if (lower === upper) return sorted[lower];
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (position - lower);
}

/** Reduce an unsorted sample to the P10-P90 knots plus the sample size. */
export function quantileSet(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const [p10, p25, p50, p75, p90] = QUANTILE_KNOTS.map((knot) => quantile(sorted, knot));
  return { p10, p25, p50, p75, p90, n: sorted.length };
}

/**
 * Inverse-transform sampling over the piecewise-linear CDF the knots describe.
 * Given rng() in [0,1], the result always lands within [p10, p90].
 */
export function sampleFromQuantiles(set, rng) {
  const values = [set.p10, set.p25, set.p50, set.p75, set.p90];
  const span = QUANTILE_KNOTS[QUANTILE_KNOTS.length - 1] - QUANTILE_KNOTS[0];
  const u = QUANTILE_KNOTS[0] + rng() * span;
  for (let index = 1; index < QUANTILE_KNOTS.length; index += 1) {
    if (u <= QUANTILE_KNOTS[index]) {
      const width = QUANTILE_KNOTS[index] - QUANTILE_KNOTS[index - 1];
      const ratio = width === 0 ? 0 : (u - QUANTILE_KNOTS[index - 1]) / width;
      return values[index - 1] + (values[index] - values[index - 1]) * ratio;
    }
  }
  return values[values.length - 1];
}
