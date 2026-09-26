import type { Metadata } from "next"
import { connection } from "next/server"

import { SiteHeader } from "@/components/site-header"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { apiFetch } from "@/lib/api"
import type { SourceStatus } from "@/lib/leads"

export const metadata: Metadata = { title: "Data sources" }

const number = new Intl.NumberFormat("en-US")
const dateTime = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/Chicago",
  dateStyle: "medium",
  timeStyle: "short",
})

function formatDate(value: string | null) {
  return value ? dateTime.format(new Date(value)) : "—"
}

function formatCount(value: number | null) {
  return value === null ? "—" : number.format(value)
}

function StatusBadge({ status }: { status: string | null }) {
  if (status === "failed") return <Badge variant="destructive">Failed</Badge>
  if (status === "success") {
    return <Badge className="bg-primary/10 text-primary">Success</Badge>
  }
  if (status === "skipped") return <Badge variant="secondary">Skipped</Badge>
  if (status === "running") return <Badge variant="outline">Running</Badge>
  return <Badge variant="outline">{status ?? "Not run"}</Badge>
}

export default async function DataPage() {
  await connection()
  const sources = await apiFetch<SourceStatus[]>("/sources")

  return (
    <>
      <SiteHeader title="Data sources" />
      <div className="flex flex-col gap-6 px-4 py-4 md:py-6 lg:px-6">
        <div className="flex flex-col gap-2">
          <p className="max-w-3xl text-sm text-muted-foreground">
            Sources refresh weekly on Sunday at 03:00 Central. Unchanged sources are skipped.
          </p>
        </div>

        <Card>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Source</TableHead>
                  <TableHead>Last status</TableHead>
                  <TableHead>Last run</TableHead>
                  <TableHead>Last success</TableHead>
                  <TableHead className="text-right">Rows</TableHead>
                  <TableHead className="text-right">Inserted / updated</TableHead>
                  <TableHead>Error</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sources.map((source) => (
                  <TableRow key={source.source_id}>
                    <TableCell className="font-mono text-xs">{source.source_id}</TableCell>
                    <TableCell><StatusBadge status={source.status} /></TableCell>
                    <TableCell>{formatDate(source.started_at)}</TableCell>
                    <TableCell>{formatDate(source.last_success_at)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatCount(source.rows)}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatCount(source.inserted)} / {formatCount(source.updated)}
                    </TableCell>
                    <TableCell>
                      {source.error ? (
                        <span className="block max-w-64 truncate text-destructive" title={source.error}>
                          {source.error}
                        </span>
                      ) : "—"}
                    </TableCell>
                  </TableRow>
                ))}
                {sources.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={7} className="py-8 text-center text-muted-foreground">
                      No data sources are configured.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </>
  )
}
