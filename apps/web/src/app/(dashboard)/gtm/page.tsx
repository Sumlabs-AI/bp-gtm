import { GtmPage } from "@/components/gtm/gtm-page"
import { SiteHeader } from "@/components/site-header"

export const metadata = { title: "GTM" }

// The home page: the list of leads is the product, the map is the lens (wiki/need-engine.md).
// `?lead=<id>` opens that lead's drawer (old /leads/<id> links redirect here).
export default async function Page(props: PageProps<"/gtm">) {
  const { lead } = await props.searchParams
  const id = Number(Array.isArray(lead) ? lead[0] : lead)
  return (
    <>
      <SiteHeader title="Who’s Most Likely to Go Battery?" />
      <GtmPage initialLead={Number.isSafeInteger(id) && id > 0 ? id : null} />
    </>
  )
}
