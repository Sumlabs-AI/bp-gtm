"use client"

import Link from "next/link"
import { RouteError } from "@/components/route-error"
import { buttonVariants } from "@/components/ui/button"

export default function GridError({ retry }: { retry: () => void }) {
  return (
    <RouteError title="Grid Zones" description="Grid data is temporarily unavailable. Try again in a moment." retry={retry}>
      <Link href="/leads" className={buttonVariants({ variant: "outline" })}>Return to leads</Link>
    </RouteError>
  )
}
