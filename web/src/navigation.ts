// Page state shared by the app shell, header and profile menu.
export type Page =
  | "home"
  | "survey"
  | "recommendations"
  | "mytickets"
  | "purchase"
  | "artist"
  | "sales";

export type MainTab = "home" | "survey" | "recommendations";

export const MAIN_TABS: { page: MainTab; label: string }[] = [
  { page: "home", label: "Discover Events" },
  { page: "survey", label: "Music Preferences" },
  { page: "recommendations", label: "Recommended for You" },
];

/** The main tab to highlight for a page; the purchase flow belongs to Discover. */
export function activeTab(page: Page): MainTab | null {
  if (page === "home" || page === "purchase") return "home";
  if (page === "survey" || page === "recommendations") return page;
  return null;
}

/** Pages that require a signed-in user outside demo mode. */
export const PRIVATE_PAGES: readonly Page[] = ["survey", "recommendations", "mytickets", "artist", "sales", "purchase"];
