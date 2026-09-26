"use client"

import { Suspense } from "react"
import Link from "next/link"
import { useSearchParams } from "next/navigation"

import { buttonVariants } from "@/components/ui/button"
import { leadReturnHref } from "@/lib/leads"

function ReturnLink() {
  const query = useSearchParams()
  return <Link href={leadReturnHref(query.get("back") ?? undefined)} className={buttonVariants({ variant: "outline" })}>Return to results</Link>
}

export function LeadReturnLink() {
  return (
    <Suspense fallback={<Link href="/leads" className={buttonVariants({ variant: "outline" })}>Return to results</Link>}>
      <ReturnLink />
    </Suspense>
  )
}
