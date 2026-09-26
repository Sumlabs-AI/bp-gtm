import { PRIORITY_HELP } from "@/lib/leads"

export function PriorityHelp() {
  return (
    <details className="max-w-2xl text-xs text-muted-foreground">
      <summary className="w-fit cursor-pointer rounded-sm focus-visible:outline-2 focus-visible:outline-ring">
        Ranking metric · How priority works
      </summary>
      <p className="mt-2 leading-relaxed">{PRIORITY_HELP}</p>
    </details>
  )
}
