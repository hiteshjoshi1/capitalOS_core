const PLATFORM_LABELS: Record<string, string> = {
  DBS_VICKERS: "DBS Vickers",
};

export function formatPlatformLabel(platform: string): string {
  return PLATFORM_LABELS[platform.toUpperCase()] ?? platform;
}
