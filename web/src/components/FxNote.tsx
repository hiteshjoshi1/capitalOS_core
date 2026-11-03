import { fxNoteText } from "../lib/fxNote";
import type { FxStatus } from "../lib/api";

/** A small, muted note under a total; renders nothing when FX is complete. */
export default function FxNote({ sources }: { sources: Array<FxStatus | null | undefined> }) {
  const text = fxNoteText(...sources);
  if (!text) return null;
  return (
    <p className="coHeroFreshness" role="note" data-testid="fx-note">
      {text}
    </p>
  );
}
