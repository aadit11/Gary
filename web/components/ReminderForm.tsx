"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";

export default function ReminderForm() {
  const router = useRouter();
  const [message, setMessage] = useState("Time to take your morning blood pressure pill.");
  const [time, setTime] = useState("08:00");
  const [recurrence, setRecurrence] = useState("daily");
  const [status, setStatus] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setStatus("Saving…");
    const res = await fetch("/api/reminders", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message, time_of_day: time, recurrence }) });
    if (res.ok) { setStatus("Saved. Gary will call at that time."); router.refresh(); } else { setStatus("Could not save: " + (await res.json()).error); }
  }

  return (
    <form onSubmit={submit}>
      <label>Reminder<input value={message} onChange={(e) => setMessage(e.target.value)} required /></label>
      <label>Time (user&apos;s local)<input type="time" value={time} onChange={(e) => setTime(e.target.value)} required /></label>
      <label>Repeat<select value={recurrence} onChange={(e) => setRecurrence(e.target.value)}><option value="daily">Every day</option><option value="weekdays">Weekdays</option><option value="weekly">Weekly</option><option value="once">Once</option></select></label>
      <button type="submit">Schedule call</button>
      {status && <div className="muted">{status}</div>}
    </form>
  );
}
