"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { WEEKDAYS } from "@/lib/profile";

export default function ReminderForm({ name }: { name: string }) {
  const router = useRouter();
  const [message, setMessage] = useState("");
  const [time, setTime] = useState("08:00");
  const [recurrence, setRecurrence] = useState("daily");
  const [weekday, setWeekday] = useState("0");
  const [status, setStatus] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setStatus("Saving…");
    const res = await fetch("/api/reminders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, time_of_day: time, recurrence, weekday: Number(weekday) }),
    });
    if (res.ok) {
      setMessage("");
      setStatus("Added. You can schedule another call below.");
      router.refresh();
    } else {
      const body = await res.json().catch(() => ({ error: "unknown" }));
      setStatus("Could not save. " + (body.error || ""));
    }
  }

  return (
    <form className="care-form" onSubmit={submit}>
      <p className="muted">Add as many calls as you need. Each one is kept.</p>
      <label>
        Words Gary should say to {name}
        <input value={message} onChange={(e) => setMessage(e.target.value)} placeholder="It's time for a glass of water." required />
      </label>
      <label>
        Time on their clock
        <input type="time" value={time} onChange={(e) => setTime(e.target.value)} required />
      </label>
      <fieldset className="often">
        <legend>How often</legend>
        {[
          ["daily", "Every day"],
          ["weekdays", "Weekdays"],
          ["weekly", "Once a week"],
          ["once", "One time"],
        ].map(([value, label]) => (
          <button key={value} type="button" className={recurrence === value ? "quiet-button on" : "quiet-button"} onClick={() => setRecurrence(value)} aria-pressed={recurrence === value}>
            {label}
          </button>
        ))}
      </fieldset>
      {recurrence === "weekly" && (
        <label>
          Which day
          <select value={weekday} onChange={(e) => setWeekday(e.target.value)} required>
            {WEEKDAYS.map((day, index) => (
              <option key={day} value={index}>{day}</option>
            ))}
          </select>
        </label>
      )}
      <button type="submit">Add this call</button>
      {status && <div className="muted">{status}</div>}
    </form>
  );
}
