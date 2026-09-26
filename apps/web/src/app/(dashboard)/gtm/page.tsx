import { GtmPage } from "@/components/gtm/gtm-page"
import { SiteHeader } from "@/components/site-header"

export const metadata = { title: "GTM" }

// The home page: the list of leads is the product, the map is the lens (wiki/need-engine.md).
export default function Page() {
  return (
    <>
      <SiteHeader title="GTM: where backup power is needed, and who needs it" />
      <GtmPage />
    </>
  )
}
