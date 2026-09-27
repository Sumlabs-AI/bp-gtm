"use client"

import * as React from "react"
import Link from "next/link"
import { DatabaseIcon, MapIcon, RadarIcon } from "lucide-react"

import { BaseLogo } from "@/components/base-logo"
import { NavMain } from "@/components/nav-main"
import { NavSecondary } from "@/components/nav-secondary"
import {
  Sidebar,
  SidebarContent,
  SidebarHeader,
  useSidebar,
} from "@/components/ui/sidebar"

const mainItems = [
  { title: "GTM", url: "/gtm", icon: RadarIcon },
  { title: "Grid Zones", url: "/grid", icon: MapIcon },
]
const operationItems = [
  { title: "Data sources", url: "/data", icon: DatabaseIcon },
]

export function AppSidebar({ ...props }: React.ComponentProps<typeof Sidebar>) {
  const { setOpenMobile } = useSidebar()

  return (
    <Sidebar collapsible="offcanvas" {...props}>
      <SidebarHeader className="px-4 pt-5 pb-4">
        <Link href="/gtm" onClick={() => setOpenMobile(false)} className="flex w-fit flex-col gap-1.5 rounded-md focus-visible:outline-2 focus-visible:outline-sidebar-ring">
          <BaseLogo className="h-7 w-auto text-sidebar-foreground" />
          <span className="pl-0.5 text-xs font-semibold tracking-[0.25em] text-sidebar-primary uppercase">Radar</span>
        </Link>
      </SidebarHeader>
      <SidebarContent>
        <NavMain items={mainItems} />
        <NavSecondary items={operationItems} className="mt-auto" />
      </SidebarContent>
    </Sidebar>
  )
}
