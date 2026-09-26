"use client"

import * as React from "react"
import Link from "next/link"
import { DatabaseIcon, MapIcon, RadarIcon, UsersIcon } from "lucide-react"

import { NavMain } from "@/components/nav-main"
import { NavSecondary } from "@/components/nav-secondary"
import {
  Sidebar,
  SidebarContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar"

const mainItems = [
  { title: "Leads", url: "/leads", icon: UsersIcon },
  { title: "Grid Zones", url: "/grid", icon: MapIcon },
]
const operationItems = [
  { title: "Data sources", url: "/data", icon: DatabaseIcon },
]

export function AppSidebar({ ...props }: React.ComponentProps<typeof Sidebar>) {
  const { setOpenMobile } = useSidebar()

  return (
    <Sidebar collapsible="offcanvas" {...props}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              size="lg"
              render={<Link href="/leads" />}
              onClick={() => setOpenMobile(false)}
            >
              <RadarIcon />
              <span>Base Radar</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <NavMain items={mainItems} />
        <NavSecondary items={operationItems} className="mt-auto" />
      </SidebarContent>
    </Sidebar>
  )
}
