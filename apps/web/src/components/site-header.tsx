import Link from "next/link"

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import { Separator } from "@/components/ui/separator"
import { SidebarTrigger } from "@/components/ui/sidebar"

export function SiteHeader({
  title,
  parent,
}: {
  title: string
  parent?: { title: string; href: string }
}) {
  return (
    <header className="flex min-h-(--header-height) shrink-0 items-center border-b">
      <div className="flex min-w-0 w-full items-center gap-1 px-4 py-2 lg:gap-2 lg:px-6">
        <SidebarTrigger className="-ml-1 shrink-0" />
        <Separator orientation="vertical" className="mx-2 h-4 data-vertical:self-auto" />
        {parent ? (
          <Breadcrumb className="min-w-0">
            <BreadcrumbList className="flex-nowrap">
              <BreadcrumbItem className="shrink-0">
                <BreadcrumbLink render={<Link href={parent.href} />}>{parent.title}</BreadcrumbLink>
              </BreadcrumbItem>
              <BreadcrumbSeparator />
              <BreadcrumbItem className="min-w-0">
                <h1 className="text-base wrap-anywhere" title={title}>
                  <BreadcrumbPage>{title}</BreadcrumbPage>
                </h1>
              </BreadcrumbItem>
            </BreadcrumbList>
          </Breadcrumb>
        ) : (
          <h1 className="truncate text-base font-medium">{title}</h1>
        )}
      </div>
    </header>
  )
}
