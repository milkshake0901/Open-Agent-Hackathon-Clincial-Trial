"use client";

// Treatments and the biomarker that measures that diagnosis (PSA for prostate cancer), on one timeline in date
// order. The comparison is a model call over those rows only.

import { useEffect, useState } from "react";
import { api, type Course, type CourseComparison } from "@/lib/api";

const longDate = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString("en-AU", { day: "numeric", month: "short", year: "numeric" });

type TreatmentItem = { subject: string; detail: string };
type ReadingItem = { name: string; value: string; unit: string | null; number: number };
type TimelinePoint = { on: string | null; treatments: TreatmentItem[]; readings: ReadingItem[] };

function pointsOf(course: Course): TimelinePoint[] {
  const byDate = new Map<string, TimelinePoint>();
  const point = (on: string | null) => {
    const key = on ?? "";
    const existing = byDate.get(key);
    if (existing) return existing;
    const created: TimelinePoint = { on, treatments: [], readings: [] };
    byDate.set(key, created);
    return created;
  };
  for (const item of course.treatments) {
    point(item.on).treatments.push({ subject: item.subject, detail: item.detail });
  }
  for (const series of course.series) {
    for (const reading of series.points) {
      point(reading.on).readings.push({
        name: series.name, value: reading.value, unit: reading.unit, number: reading.number,
      });
    }
  }
  return [...byDate.values()].sort((a, b) => {
    if (a.on === b.on) return 0;
    if (!a.on) return 1;
    if (!b.on) return -1;
    return a.on < b.on ? -1 : 1;
  });
}

export function TreatmentCourse({ patientId, runId }: { patientId: string; runId?: string }) {
  const [course, setCourse] = useState<Course | null>(null);
  const [comparison, setComparison] = useState<CourseComparison | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.course(patientId, runId).then(setCourse).catch(() => setCourse(null));
  }, [patientId, runId]);

  if (!course || (course.treatments.length === 0 && course.series.length === 0)) return null;
  const series = course.series[0];
  const marker = course.marker ?? series?.name ?? "the marker";
  const peak = Math.max(1, ...(series?.points.map((point) => point.number) ?? []));
  const points = pointsOf(course);

  async function compare() {
    setBusy(true);
    setError(null);
    try {
      setComparison(await api.compareCourse(patientId, runId));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="treatment-course" className="rounded-xl border border-border bg-surface p-5 flex flex-col gap-4">
      <h2 id="treatment-course" className="text-lg font-semibold">Treatment timeline</h2>
      <p className="text-muted">
        Built from the letter. Treatments and {marker} readings that share a date are one point.
      </p>
      <ol className="flex flex-col gap-3 border-l border-border pl-4">
        {points.map((point) => (
          <li key={point.on ?? "undated"} className="relative">
            <span className={`absolute -left-[1.3rem] top-1.5 h-2.5 w-2.5 rounded-full ${point.readings.length ? "border-2 border-accent bg-surface" : "bg-accent"}`} />
            <p className="text-sm text-muted">{point.on ? longDate(point.on) : "Date not on the letter"}</p>
            <ul className="flex flex-col gap-1">
              {point.treatments.map((item) => (
                <li key={item.subject}>
                  <p className="font-medium first-letter:uppercase">{item.subject}</p>
                  {item.detail.toLowerCase() !== item.subject.toLowerCase() && <p>{item.detail}</p>}
                </li>
              ))}
            </ul>
            {point.readings.map((reading) => (
              <div key={reading.name} className="mt-2">
                <p className="font-medium">{reading.name} {reading.value}{reading.unit ? ` ${reading.unit}` : ""}</p>
                <span className="mt-1 block h-1.5 max-w-xs rounded-full bg-border">
                  <span className="block h-1.5 rounded-full bg-accent" style={{ width: `${Math.max(8, (reading.number / peak) * 100)}%` }} />
                </span>
              </div>
            ))}
          </li>
        ))}
      </ol>
      <button type="button" onClick={compare} disabled={busy || !series}
              className="min-h-12 self-start rounded-lg bg-accent px-5 text-base font-semibold text-white dark:text-black disabled:opacity-60">
        {busy ? "Comparing…" : `Compare treatments with ${marker}`}
      </button>
      {error && <p role="alert" className="text-red-700 dark:text-red-400">{error}</p>}
      {comparison && (
        <div className="flex flex-col gap-2" role="status">
          <p>{comparison.summary}</p>
          {comparison.notes.length > 0 && (
            <ul className="flex flex-col gap-2">
              {comparison.notes.map((note) => (
                <li key={`${note.treatment}-${note.on}`} className="rounded-lg border border-border p-3">
                  <p className="font-medium first-letter:uppercase">{note.treatment}, {longDate(note.on)}</p>
                  <p>{note.change} ({note.value})</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
