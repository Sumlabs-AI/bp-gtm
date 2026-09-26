import { InfoIcon } from "lucide-react"

import { Disclosure } from "@/components/disclosure"
import { ConsumptionChart } from "@/components/leads/consumption-chart"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty"
import { Separator } from "@/components/ui/separator"
import { formatKwh, type LeadDetail } from "@/lib/leads"

export function ConsumptionCard({ lead }: { lead: LeadDetail }) {
  const { consumption } = lead
  const missingInput = "not on record (typical value used)"
  const pool = lead.drivers.find((driver) => driver.key === "pool")?.value
  const inputs = [
    ["Heated area", lead.heated_sqft === null ? missingInput : `${Math.round(lead.heated_sqft).toLocaleString("en-US")} sqft`],
    ["Year built", lead.year_built?.toString() ?? missingInput],
    ["Stories", lead.stories?.toString() ?? missingInput],
    ["Bedrooms", lead.bedrooms?.toString() ?? missingInput],
    ["Pool", pool === true ? "Yes, recorded" : pool === false ? "No pool recorded" : missingInput],
  ]

  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Estimated electricity use</CardTitle>
        <Badge variant="secondary">Property-based estimate · no bill</Badge>
      </CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-4">
        {consumption === null ? (
          <Empty>
            <EmptyHeader>
              <EmptyTitle>Estimate unavailable</EmptyTitle>
              <EmptyDescription>Estimated Consumption is not available for this home yet.</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <>
            <div className="flex flex-col gap-1 tabular-nums">
              <p className="text-3xl font-semibold">≈ {formatKwh(consumption.annual_kwh)}/yr</p>
              <p className="text-sm">≈ {formatKwh(Math.round(consumption.annual_kwh / 120) * 10)}/month on average</p>
              <p className="text-xs text-muted-foreground">Likely range {Math.round(consumption.low_kwh).toLocaleString("en-US")}–{formatKwh(consumption.high_kwh)}/yr</p>
            </div>
            <ConsumptionChart consumption={consumption} />
            <dl className="grid gap-3 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-xs text-muted-foreground">Heating</dt>
                <dd className="mt-1 tabular-nums">
                  {consumption.electric_heat_prob >= 0.6 ? "Likely electric" : consumption.electric_heat_prob <= 0.4 ? "Likely gas" : "Uncertain"}
                  {" · "}{Math.round(consumption.electric_heat_prob * 100)}% chance electric
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Peak demand</dt>
                <dd className="mt-1 tabular-nums">
                  ~{Math.round(consumption.peak_summer_kw)} kW summer · ~{Math.round(consumption.peak_winter_kw)} kW winter
                  <span className="block text-xs text-muted-foreground">(this home, highest day)</span>
                </dd>
              </div>
            </dl>
          </>
        )}
        <Disclosure title="How this is estimated" icon={InfoIcon} className="text-xs text-muted-foreground">
          <p>
            Property-based estimate for a typical weather year, with no bill or meter data.
            NREL ResStock simulations of Harris County single-family homes are matched on heated area,
            year built, stories, bedrooms and pool, then scaled to EIA survey bills (RECS 2020).
            Heating fuel is unknown for this home, so electric and gas heat are mixed by the Census
            share of electric heat in its block group. Monthly shape comes from ERCOT&apos;s Houston
            residential load profiles (2019–2025 average).
          </p>
          <p>
            Expect roughly ±30–40% on the annual total for an individual home, and more on peaks.
            Area totals are much closer. Not metered, not a bill, not customer savings.
          </p>
          <Separator />
          <p className="font-medium text-foreground">Inputs for this home</p>
          <dl className="grid gap-3 sm:grid-cols-2">
            {inputs.map(([label, value]) => <div key={label}>
              <dt>{label}</dt>
              <dd className="mt-1 text-foreground tabular-nums">{value}</dd>
            </div>)}
          </dl>
        </Disclosure>
      </CardContent>
    </Card>
  )
}
