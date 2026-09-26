import { LeadReturnLink } from "@/components/leads/lead-return-link"
import { SiteHeader } from "@/components/site-header"
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty"

export default function LeadNotFound() {
  return (
    <>
      <SiteHeader title="Lead unavailable" parent={{ title: "Leads", href: "/leads" }} />
      <Empty>
        <EmptyHeader>
          <EmptyTitle>Lead not found</EmptyTitle>
          <EmptyDescription>This home may no longer be eligible, or the link may be incorrect.</EmptyDescription>
        </EmptyHeader>
        <EmptyContent><LeadReturnLink /></EmptyContent>
      </Empty>
    </>
  )
}
