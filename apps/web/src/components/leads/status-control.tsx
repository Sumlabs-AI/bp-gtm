"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"

import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { apiFetch } from "@/lib/api"
import type { LeadDetail, LeadStatus } from "@/lib/leads"

const statuses: LeadStatus[] = ["new", "reviewed", "qualified", "excluded"]

export function StatusControl({ id, status }: { id: number; status: LeadStatus }) {
  const router = useRouter()
  const [selected, setSelected] = useState<LeadStatus>(status)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save() {
    setSaving(true)
    setError(null)
    try {
      await apiFetch<LeadDetail>(`/leads/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: selected }),
      })
      router.refresh()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not update status.")
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor="lead-status">Lead status</Label>
      <div className="flex items-center gap-2">
        <Select value={selected} onValueChange={(value) => value && setSelected(value as LeadStatus)}>
          <SelectTrigger id="lead-status" aria-label="Lead status" className="min-w-32">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {statuses.map((option) => (
              <SelectItem key={option} value={option}>
                {option[0].toUpperCase() + option.slice(1)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button onClick={save} disabled={saving || selected === status}>
          {saving ? "Saving…" : "Save"}
        </Button>
      </div>
      {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
    </div>
  )
}
