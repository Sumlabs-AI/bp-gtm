import { scoreColor } from "@/lib/grid"
import type { WeatherComponent } from "@/lib/need"

const through = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" })

function Score({ value }: { value: number | null }) {
  if (value === null) return <span className="text-muted-foreground">—</span>
  return (
    <span className="rounded-md px-2 py-0.5 font-semibold tabular-nums" style={{ background: scoreColor(value) }}>
      {value.toFixed(0)}
    </span>
  )
}

function Row({ label, value }: { label: string; value: number }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-right tabular-nums">{value.toLocaleString("en-US")}</dd>
    </>
  )
}

export function WeatherBreakdown({ weather }: { weather: WeatherComponent }) {
  const storm = weather.stormExposure
  const temperature = weather.temperatureExtremesExposure
  return (
    <section className="flex flex-col gap-4 px-4 text-sm">
      <div className="flex items-center justify-between">
        <h3 className="font-medium">Weather Need</h3>
        <Score value={weather.score} />
      </div>

      {storm && (
        <div className="flex flex-col gap-2 rounded-lg border p-3">
          <div className="flex items-center justify-between">
            <span className="font-medium">Storm Exposure</span>
            <Score value={storm.score} />
          </div>
          <p className="text-xs text-muted-foreground">
            Days under severe thunderstorm, tornado or extreme wind warnings, Texas percentile. Measured for the ~36 km²
            area <span className="font-mono">{storm.sourceCell}</span> (H3 res {storm.resolution}) containing this Cell.
          </p>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
            <Row label="Warning-days (5 y)" value={storm.metrics.warningDays5y} />
            <Row label="Warning-days (365 d)" value={storm.metrics.warningDays365d} />
            <Row label="Severe thunderstorm warnings" value={storm.metrics.severeThunderstormWarnings5y} />
            <Row label="Tornado warnings" value={storm.metrics.tornadoWarnings5y} />
          </dl>
          <p className="text-[11px] text-muted-foreground">
            {storm.source} · history through {through(storm.dataThrough)}
          </p>
          {storm.caveats.map((c) => (
            <p key={c} className="text-[11px] text-muted-foreground">{c}</p>
          ))}
        </div>
      )}

      {temperature && (
        <div className="flex flex-col gap-2 rounded-lg border p-3">
          <div className="flex items-center justify-between">
            <span className="font-medium">Temperature Extremes</span>
            <Score value={temperature.score} />
          </div>
          <p className="text-xs text-muted-foreground">
            Measured days of dangerous heat or cold during an outage, county-level Texas percentile.
          </p>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
            <Row label="Days ≥ 100°F (5 y)" value={temperature.metrics.heatDays100F5y} />
            <Row label="Days ≤ 28°F (5 y)" value={temperature.metrics.coldDays28F5y} />
            <Row label="Days ≥ 95°F (context)" value={temperature.metrics.heatDays95F5y} />
            <Row label="Days ≤ 32°F (context)" value={temperature.metrics.coldDays32F5y} />
          </dl>
          <p className="text-[11px] text-muted-foreground">
            {temperature.source} · history through {through(temperature.dataThrough)}
          </p>
          {temperature.limitations.map((l) => (
            <p key={l} className="text-[11px] text-muted-foreground">{l}</p>
          ))}
        </div>
      )}

      {weather.notes.map((note) => (
        <p key={note} className="text-xs text-muted-foreground">
          {note}
        </p>
      ))}
    </section>
  )
}
