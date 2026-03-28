import type { FormEvent } from "react";

export type PlatformDraft = {
  code: string;
  name: string;
  platform_type: string;
  country: string;
  website: string;
};

type PlatformDetailsFormProps = {
  value: PlatformDraft;
  platformTypes: string[];
  platformCountries: string[];
  onChange: (next: PlatformDraft) => void;
  onSubmit: (e: FormEvent<HTMLFormElement>) => void;
  onCancel?: () => void;
  submitLabel?: string;
};

export default function PlatformDetailsForm({
  value,
  platformTypes,
  platformCountries,
  onChange,
  onSubmit,
  onCancel,
  submitLabel = "Save platform",
}: PlatformDetailsFormProps) {
  return (
    <form className="formGrid" onSubmit={onSubmit}>
      <label className="field">
        <span className="label">Code</span>
        <input
          className="input"
          type="text"
          value={value.code}
          aria-label="Platform Code"
          onChange={(e) => onChange({ ...value, code: e.target.value })}
          placeholder="e.g. DBS"
          required
        />
      </label>
      <label className="field">
        <span className="label">Name</span>
        <input
          className="input"
          type="text"
          value={value.name}
          aria-label="Platform Name"
          onChange={(e) => onChange({ ...value, name: e.target.value })}
          placeholder="e.g. DBS Bank"
          required
        />
      </label>
      <label className="field">
        <span className="label">Platform Type</span>
        <select
          className="input"
          value={value.platform_type}
          aria-label="Platform Type"
          onChange={(e) => onChange({ ...value, platform_type: e.target.value })}
          required
        >
          <option value="" disabled>
            Select type
          </option>
          {platformTypes.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        <span className="label">Country</span>
        {platformCountries.length > 0 ? (
          <select
            className="input"
            value={value.country}
            aria-label="Platform Country"
            onChange={(e) => onChange({ ...value, country: e.target.value })}
            required
          >
            <option value="" disabled>
              Select country
            </option>
            {platformCountries.map((country) => (
              <option key={country} value={country}>
                {country}
              </option>
            ))}
          </select>
        ) : (
          <input
            className="input"
            type="text"
            value={value.country}
            aria-label="Platform Country"
            onChange={(e) => onChange({ ...value, country: e.target.value })}
            placeholder="e.g. SG"
            required
          />
        )}
      </label>
      <label className="field">
        <span className="label">Website</span>
        <input
          className="input"
          type="url"
          value={value.website}
          aria-label="Platform Website"
          onChange={(e) => onChange({ ...value, website: e.target.value })}
          placeholder="https://www.example.com"
        />
      </label>
      <div className="actions">
        <button className="btn" type="submit">
          {submitLabel}
        </button>
        {onCancel ? (
          <button className="btn" type="button" onClick={onCancel}>
            Cancel
          </button>
        ) : null}
      </div>
    </form>
  );
}
