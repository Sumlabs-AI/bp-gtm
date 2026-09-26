"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"

import { Button } from "@/components/ui/button"
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { apiFetch } from "@/lib/api"
import { STATUS_LABELS, type LeadDetail, type LeadStatus } from "@/lib/leads"

const statuses: LeadStatus[] = ["new", "reviewed", "qualified", "excluded"]
const items = statuses.map((value) => ({ value, label: STATUS_LABELS[value] }))

export function StatusControl({ id, status }: { id: number; status: LeadStatus }) {
  const router = useRouter()
  const [selected, setSelected] = useState<LeadStatus>(status)
  const [savedStatus, setSavedStatus] = useState<LeadStatus>(status)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  async function save() {
    setSaving(true)
    setError(null)
    setMessage(null)
    try {
      const updated = await apiFetch<LeadDetail>(`/leads/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: selected }),
      })
      setSavedStatus(updated.status)
      setSelected(updated.status)
      setMessage(`Status saved as ${STATUS_LABELS[updated.status]}.`)
      router.refresh()
    } catch {
      setError("Could not save the status. Try again.")
    } finally {
      setSaving(false)
    }
  }

  return (
    <FieldGroup>
      <Field data-disabled={saving}>
        <FieldLabel htmlFor="lead-status">Review status</FieldLabel>
        <div className="flex flex-wrap items-center gap-2">
          <Select items={items} value={selected} disabled={saving} onValueChange={(value) => {
            if (!value) return
            setSelected(value as LeadStatus)
            setError(null)
            setMessage(null)
          }}>
            <SelectTrigger id="lead-status" className="min-w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {items.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
          <Button onClick={save} disabled={saving || selected === savedStatus}>
            {saving ? "Saving…" : "Save status"}
          </Button>
        </div>
        {error && <FieldError>{error}</FieldError>}
        {message && <p role="status" className="text-sm text-muted-foreground">{message}</p>}
      </Field>
    </FieldGroup>
  )
}
