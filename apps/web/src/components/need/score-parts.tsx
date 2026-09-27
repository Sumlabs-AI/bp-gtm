import { scoreColor } from "@/lib/grid"

// Shared pieces of the Need Component breakdowns (Outage, Weather).

export const historyThrough = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" })

export function Score({ value }: { value: number | null }) {
  if (value === null) return <span className="text-muted-foreground">—</span>
  return (
    <span className="rounded-md px-2 py-0.5 font-semibold tabular-nums" style={{ background: scoreColor(value) }}>
      {value.toFixed(0)}
    </span>
  )
}

export function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-right tabular-nums">{value}</dd>
    </>
  )
}
