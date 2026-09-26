"use client"

import { LeadReturnLink } from "@/components/leads/lead-return-link"
import { RouteError } from "@/components/route-error"

export default function LeadError({ retry }: { retry: () => void }) {
  return (
    <RouteError title="Lead details" description="This home's details are temporarily unavailable. Try again or return to your results." retry={retry}>
      <LeadReturnLink />
    </RouteError>
  )
}
