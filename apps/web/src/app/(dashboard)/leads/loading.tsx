import { SiteHeader } from "@/components/site-header"
import { Skeleton } from "@/components/ui/skeleton"

export default function LeadsLoading() {
  return (
    <>
      <SiteHeader title="Leads" />
      <div role="status" aria-label="Loading leads" className="flex flex-col gap-5 px-4 py-6 lg:px-6">
        <span className="sr-only">Loading leads…</span>
        <Skeleton className="h-5 w-64 max-w-full" />
        <Skeleton className="h-24 w-full" />
        {Array.from({ length: 6 }, (_, index) => <Skeleton key={index} className="h-24 w-full md:h-16" />)}
      </div>
    </>
  )
}
