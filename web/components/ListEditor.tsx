"use client";

// Small variable-length list editors used by onboarding and the profile: free-text items
// (dietary restrictions) and labelled places (name + address).

import type { Place } from "@/lib/profile";

export function TextList({ items, onChange, placeholder, addLabel }: { items: string[]; onChange: (next: string[]) => void; placeholder: string; addLabel: string }) {
  return (
    <div className="list-editor">
      {items.map((item, i) => (
        <div className="list-row" key={i}>
          <input value={item} placeholder={placeholder} onChange={(e) => onChange(items.map((v, j) => (j === i ? e.target.value : v)))} />
          <button type="button" className="quiet-button small" aria-label="Remove" onClick={() => onChange(items.filter((_, j) => j !== i))}>×</button>
        </div>
      ))}
      <button type="button" className="quiet-button small add" onClick={() => onChange([...items, ""])}>+ {addLabel}</button>
    </div>
  );
}

export function PlaceList({ items, onChange }: { items: Place[]; onChange: (next: Place[]) => void }) {
  return (
    <div className="list-editor">
      {items.map((place, i) => (
        <div className="list-row place" key={i}>
          <input value={place.label} placeholder="Name, e.g. Dr. Patel" onChange={(e) => onChange(items.map((v, j) => (j === i ? { ...v, label: e.target.value } : v)))} />
          <input value={place.address} placeholder="Address" onChange={(e) => onChange(items.map((v, j) => (j === i ? { ...v, address: e.target.value } : v)))} />
          <button type="button" className="quiet-button small" aria-label="Remove" onClick={() => onChange(items.filter((_, j) => j !== i))}>×</button>
        </div>
      ))}
      <button type="button" className="quiet-button small add" onClick={() => onChange([...items, { label: "", address: "" }])}>+ Add a place</button>
    </div>
  );
}
