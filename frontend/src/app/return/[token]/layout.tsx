import type { Metadata } from "next";

// The token is in this URL: never send it on as a Referer, never index the page.
export const metadata: Metadata = {
  title: "Your record · TrialMatch",
  referrer: "no-referrer",
  robots: { index: false, follow: false },
};

export default function ReturnLayout({ children }: LayoutProps<"/return/[token]">) {
  return children;
}
