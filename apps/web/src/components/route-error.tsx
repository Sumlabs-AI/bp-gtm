"use client"

import { SiteHeader } from "@/components/site-header"
import { Button } from "@/components/ui/button"
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty"

export function RouteError({ title, description, retry, children }: {
  title: string
  description: string
  retry: () => void
  children?: React.ReactNode
}) {
  return (
    <>
      <SiteHeader title={title} />
      <Empty role="alert">
        <EmptyHeader>
          <EmptyTitle>Could not load {title.toLowerCase()}</EmptyTitle>
          <EmptyDescription>{description}</EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <Button onClick={retry}>Try again</Button>
          {children}
        </EmptyContent>
      </Empty>
    </>
  )
}
