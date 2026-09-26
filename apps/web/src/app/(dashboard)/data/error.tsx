"use client"

import { RouteError } from "@/components/route-error"

export default function DataError({ retry }: { retry: () => void }) {
  return <RouteError title="Data sources" description="Source health is temporarily unavailable. Try loading it again." retry={retry} />
}
