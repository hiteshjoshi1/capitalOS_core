import { useEffect } from "react";

type SuccessBannerProps = {
  message: string;
  onDismiss: () => void;
  durationMs?: number;
};

export default function SuccessBanner({ message, onDismiss, durationMs = 2400 }: SuccessBannerProps) {
  useEffect(() => {
    const timer = setTimeout(onDismiss, durationMs);
    return () => clearTimeout(timer);
  }, [onDismiss, durationMs, message]);

  return (
    <div className="successBanner successBannerDot" role="status">
      <span className="successBannerDotIcon" aria-hidden="true" />
      <span>{message}</span>
    </div>
  );
}
