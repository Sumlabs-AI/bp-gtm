import { SiteHeader } from "@/components/site-header"
import { Skeleton } from "@/components/ui/skeleton"

export default function GridLoading() {
  return (
    <>
      <SiteHeader title="Grid Zones" />
      <div role="status" aria-label="Loading grid zones" className="flex flex-col gap-6 px-4 py-6 lg:px-6">
        <span className="sr-only">Loading grid zones…</span>
        <Skeleton className="h-5 w-96 max-w-full" />
        <div className="grid gap-6 xl:grid-cols-5">
          <Skeleton className="h-80 w-full xl:col-span-3 xl:h-[560px]" />
          <div className="flex flex-col gap-4 xl:col-span-2">
            {Array.from({ length: 4 }, (_, index) => <Skeleton key={index} className="h-28 w-full" />)}
          </div>
        </div>
      </div>
    </>
  )
}
