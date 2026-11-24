import type { ReactNode } from "react";
import "./FoldSection.css";

/**
 * A page section that folds on a phone (#474, V21). With `fold` off it is a plain
 * <section>; with it on, a <details> whose <summary> is the section's own heading, so a
 * long page of charts reads as a list of titles (Enter or Space opens one).
 */
export default function FoldSection({
  fold,
  defaultOpen = false,
  heading,
  ariaLabel,
  children,
}: {
  fold: boolean;
  defaultOpen?: boolean;
  heading: ReactNode;
  ariaLabel?: string;
  children: ReactNode;
}) {
  if (!fold) {
    return (
      <section aria-label={ariaLabel}>
        {heading}
        {children}
      </section>
    );
  }
  return (
    <details className="foldSection" open={defaultOpen} aria-label={ariaLabel}>
      <summary className="foldSectionSummary">
        {heading}
        <span className="foldSectionChevron" aria-hidden="true" />
      </summary>
      {children}
    </details>
  );
}
