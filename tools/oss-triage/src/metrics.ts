/** 95% Wilson interval for k correct out of n. */
export function wilson(k: number, n: number): [number, number] {
  if (n === 0) return [0, 1];
  const z = 1.96;
  const p = k / n;
  const d = 1 + (z * z) / n;
  const centre = (p + (z * z) / (2 * n)) / d;
  const half = (z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))) / d;
  return [centre - half, centre + half];
}

export type Scored = { margin: number; correct: boolean };

/** Lowest margin at which the items at or above it reach `target` accuracy, or Infinity if none do. */
export function thresholdFor(items: Scored[], target: number, minItems = 10): number {
  const sorted = [...items].sort((a, b) => b.margin - a.margin);
  let correct = 0;
  let best = Infinity;
  sorted.forEach((item, i) => {
    if (item.correct) correct++;
    const next = sorted[i + 1];
    if (next?.margin === item.margin) return;
    if (i + 1 >= minItems && correct / (i + 1) >= target) best = item.margin;
  });
  return best;
}

export type Held = { routed: number; correct: number; total: number };

/**
 * Sets each fold's threshold on the other folds, so no issue helps pick the threshold it is judged
 * by. Folds are fixed by issue number, so every approach is scored on the same split.
 */
export function crossFit<T extends Scored & { number: number }>(items: T[], target: number, folds = 5): Held {
  const held: Held = { routed: 0, correct: 0, total: items.length };
  const foldOf = (number: number) => (number * 2654435761) % 2 ** 32 % folds;
  for (let fold = 0; fold < folds; fold++) {
    const threshold = thresholdFor(items.filter((i) => foldOf(i.number) !== fold), target);
    for (const item of items.filter((i) => foldOf(i.number) === fold && i.margin >= threshold)) {
      held.routed++;
      if (item.correct) held.correct++;
    }
  }
  return held;
}

/**
 * Exact two-sided McNemar test: of the issues only one of two methods got right, how surprising is
 * the split if neither is better? Compares methods on the same issues, so it beats two intervals.
 */
export function mcnemar(onlyA: number, onlyB: number): number {
  const n = onlyA + onlyB;
  let tail = 0;
  let term = 0.5 ** n;
  for (let k = 0; k <= Math.min(onlyA, onlyB); k++) {
    tail += term;
    term *= (n - k) / (k + 1);
  }
  return Math.min(1, 2 * tail);
}
