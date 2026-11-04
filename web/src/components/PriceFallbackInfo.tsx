import { useId, useState } from "react";

import { priceFallbackMessage } from "../lib/priceFallback";

// D-21 (#124, #144): the "i" next to a holding priced at its own statement price.

type Props = {
  symbol: string;
  reason: string;
  asOf?: string | null;
  /** The platform whose statement priced it (default IBKR). */
  platform?: string | null;
};

export default function PriceFallbackInfo({ symbol, reason, asOf, platform }: Props) {
  const [open, setOpen] = useState(false);
  const noteId = useId();
  return (
    <span className="priceFallbackInfo">
      <button
        type="button"
        className="priceFallbackInfoBtn"
        aria-label={`Why is ${symbol}'s price stale?`}
        aria-expanded={open}
        aria-controls={noteId}
        onClick={() => setOpen((value) => !value)}
      >
        i
      </button>
      {open && (
        <span id={noteId} className="priceFallbackInfoNote" role="note">
          {priceFallbackMessage(symbol, reason, asOf, platform)}
        </span>
      )}
    </span>
  );
}
