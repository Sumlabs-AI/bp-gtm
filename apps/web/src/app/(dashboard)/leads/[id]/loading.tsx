import { SiteHeader } from "@/components/site-header"
import { Skeleton } from "@/components/ui/skeleton"

export default function LeadLoading() {
  return (
    <>
      <SiteHeader title="Lead details" parent={{ title: "Leads", href: "/leads" }} />
      <div role="status" aria-label="Loading lead details" className="flex flex-col gap-6 px-4 py-6 lg:px-6">
        <span className="sr-only">Loading lead details…</span>
        <Skeleton className="h-9 w-96 max-w-full" />
        <div className="grid gap-4 lg:grid-cols-2">
          <Skeleton className="h-44 w-full" />
          <Skeleton className="h-44 w-full" />
        </div>
        <Skeleton className="h-64 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    </>
  )
}
