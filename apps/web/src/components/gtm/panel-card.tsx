import type { ReactNode } from "react"
import { ChevronRightIcon } from "lucide-react"

/**
 * A collapsed drawer card: title and headline value on one line, the full block on open.
 * The wrapped Need blocks and the consumption card carry their own heading; it is hidden
 * here because the summary line already says it.
 */
export function PanelCard({ title, value, defaultOpen, children }: {
  title: string
  value: ReactNode
  defaultOpen?: boolean
  children: ReactNode
}) {
  return (
    <details open={defaultOpen} className="group mx-4 rounded-lg border open:border-primary/30">
      <summary className="flex cursor-pointer list-none items-center gap-2 rounded-lg px-3 py-2.5 text-sm hover:bg-muted/50 group-open:rounded-b-none group-open:bg-accent group-open:text-accent-foreground group-open:hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring [&::-webkit-details-marker]:hidden">
        <ChevronRightIcon className="size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-90 group-open:text-primary" aria-hidden />
        <span className="min-w-0 font-medium">{title}</span>
        <span className="ml-auto shrink-0 text-xs">{value}</span>
      </summary>
      <div className="border-t py-3 group-open:border-primary/20 [&>[data-slot=card]]:bg-transparent [&>[data-slot=card]]:py-0 [&>[data-slot=card]]:ring-0 [&>section]:px-3 [&>section>:first-child]:hidden [&_[data-slot=card-header]]:hidden">
        {children}
      </div>
    </details>
  )
}

/** A short text value in the summary line, coloured by kind (official, our reading, calm). */
export function Tag({ tone, children }: { tone: "official" | "derived" | "calm" | "stale"; children: ReactNode }) {
  const tones = {
    official: "bg-red-600 text-white",
    derived: "border border-dashed border-amber-500 text-amber-700",
    calm: "text-muted-foreground",
    stale: "border border-amber-500 text-amber-700",
  }
  return <span className={`rounded-md px-2 py-0.5 font-medium ${tones[tone]}`}>{children}</span>
}
