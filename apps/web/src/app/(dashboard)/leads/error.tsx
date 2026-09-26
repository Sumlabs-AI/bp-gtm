"use client"

import { RouteError } from "@/components/route-error"

export default function LeadsError({ retry }: { retry: () => void }) {
  return <RouteError title="Leads" description="Lead data is temporarily unavailable. Your filters are still in the address bar; try loading them again." retry={retry} />
}
