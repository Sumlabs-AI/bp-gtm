import { CellMap } from "@/components/need/cell-map"
import { Badge } from "@/components/ui/badge"

export default function NeedPage() {
  return (
    <div className="flex flex-col gap-6 px-4 py-4 md:py-6 lg:px-6">
      <div className="flex flex-col gap-2">
        <h2 className="text-2xl font-semibold tracking-tight">Where is backup power needed?</h2>
        <p className="max-w-3xl text-sm text-muted-foreground">
          Baseline Need: how much structural reason a place has to benefit from backup power
          (outage history and weather exposure combined, Texas percentile). Live panels show what
          is happening now. It is not a purchase likelihood. Click a Cell to see why.
        </p>
        <div className="flex flex-wrap gap-2">
          <Badge variant="outline">Resolution: H3 8</Badge>
          <Badge variant="outline">Markets: Houston, Austin</Badge>
          <Badge variant="outline">Colour: Baseline / Outage / Weather Need</Badge>
        </div>
      </div>
      <CellMap className="h-[640px]" />
    </div>
  )
}
