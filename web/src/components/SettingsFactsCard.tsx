import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { useApiResource } from "../lib/useApiResource";

function ordinal(n: number): string {
  const rem100 = n % 100;
  if (rem100 >= 11 && rem100 <= 13) return `${n}th`;
  return `${n}${({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[n % 10] ?? "th"}`;
}

/**
 * Settings → How CapitalOS counts (#399, U24): the server settings behind the numbers, read-only
 * here. The month's snapshot day and the default upload cadence come from the server's
 * configuration; each source's own cadence is set in Data Hub → Accounts & sources; the
 * currency list is the shared one from /currencies.
 */
export default function SettingsFactsCard() {
  const facts = useApiResource("settingsFacts", () => api.settingsFacts());
  const currencies = useApiResource("currencies", () => api.currencies());
  const f = facts.data;
  const codes = (currencies.data ?? []).map((c) => c.code).filter(Boolean);
  return (
    <div className="card settingsCard" aria-labelledby="settings-facts-title">
      <div className="cardTitle" id="settings-facts-title">How CapitalOS counts</div>
      {facts.error && !f ? <p className="muted">Couldn't load these settings.</p> : null}
      {f ? (
        <dl className="settingsFacts">
          <div>
            <dt>A month</dt>
            <dd>
              {f.snapshot_day === 1
                ? "is the calendar month: its closing snapshot is taken on the 1st of the next month."
                : `closes on the ${ordinal(f.snapshot_day)}: month-end snapshots are taken on that day.`}{" "}
              <span className="muted">Set on the server (SNAPSHOT_DAY).</span>
            </dd>
          </div>
          <div>
            <dt>Overdue</dt>
            <dd>
              An upload is due every {f.upload_stale_days} days unless its source has its own schedule.{" "}
              <Link to="/operations/sources">Change a source's schedule in Data Hub → Accounts &amp; sources</Link>.
            </dd>
          </div>
          <div>
            <dt>Currencies</dt>
            <dd>
              {codes.length ? codes.join(", ") : "None yet"}.{" "}
              <span className="muted">Everything can be shown in {f.base_currencies.join(", ")} (Timezone and currency above).</span>
            </dd>
          </div>
        </dl>
      ) : null}
    </div>
  );
}
