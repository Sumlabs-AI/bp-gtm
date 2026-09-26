import type { ReactNode } from "react"
import { ChevronRightIcon, type LucideIcon } from "lucide-react"

import { cn } from "@/lib/utils"

export function Disclosure({ title, icon: Icon, children, className }: {
  title: string
  icon: LucideIcon
  children: ReactNode
  className?: string
}) {
  return (
    <details className={cn("group min-w-0 rounded-lg border", className)}>
      <summary className="flex cursor-pointer list-none items-center gap-2 rounded-lg px-3 py-2.5 text-sm font-medium text-foreground hover:bg-muted/50 focus-visible:outline-2 focus-visible:outline-ring [&::-webkit-details-marker]:hidden">
        <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
        <span className="min-w-0">{title}</span>
        <ChevronRightIcon className="ml-auto size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-90" aria-hidden />
      </summary>
      <div className="flex min-w-0 flex-col gap-3 border-t px-3 py-3 leading-relaxed">
        {children}
      </div>
    </details>
  )
}
