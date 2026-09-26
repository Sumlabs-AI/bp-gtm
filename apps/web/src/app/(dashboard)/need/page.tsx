import { redirect } from "next/navigation"

// The Need map now lives on the GTM page, as its filter.
export default function NeedPage() {
  redirect("/gtm")
}
