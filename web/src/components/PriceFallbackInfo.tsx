import { useId, useState } from "react";

import { priceFallbackMessage } from "../lib/priceFallback";

// #124: the "i" next to an IBKR holding priced at IBKR's statement price.

type Props = {
  symbol: string;
  reason: string;
  asOf?: string | null;
};

export default function PriceFallbackInfo({ symbol, reason, asOf }: Props) {
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
          {priceFallbackMessage(symbol, reason, asOf)}
        </span>
      )}
    </span>
  );
}
