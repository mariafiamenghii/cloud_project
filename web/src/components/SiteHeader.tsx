import { useEffect, useId, useState } from "react";
import logo from "../assets/front-row-logo.png";
import { MAIN_TABS, activeTab, type Page } from "../navigation";
import ProfileMenu, { type Account } from "./ProfileMenu";

type Props = {
  currentPage: Page;
  onNavigate: (page: Page) => void;
  account?: Account;
  login?: { label: string; disabled: boolean; onClick: () => void };
};

export function BrandLogo() {
  return (
    <span className="brand-logo">
      <img src={logo} alt="FRONT ROW" width={2000} height={2000} />
    </span>
  );
}

export default function SiteHeader({ currentPage, onNavigate, account, login }: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const navId = useId();
  const selected = activeTab(currentPage);

  // The compact menu closes with Escape and whenever the page changes.
  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setMenuOpen(false);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [menuOpen]);

  function go(page: Page) {
    setMenuOpen(false);
    onNavigate(page);
  }

  return (
    <header className="site-header">
      <div className="site-header-inner">
        <button type="button" className="brand" onClick={() => go("home")} aria-label="FRONT ROW home: Discover Events">
          <BrandLogo />
        </button>

        <button
          type="button"
          className="nav-toggle"
          aria-expanded={menuOpen}
          aria-controls={navId}
          onClick={() => setMenuOpen((open) => !open)}
        >
          <span className="nav-toggle-icon" aria-hidden="true" />
          <span className="visually-hidden">{menuOpen ? "Close navigation" : "Open navigation"}</span>
        </button>

        <nav id={navId} className={`main-nav${menuOpen ? " is-open" : ""}`} aria-label="Main navigation">
          <ul>
            {MAIN_TABS.map((tab) => (
              <li key={tab.page}>
                <button
                  type="button"
                  className="main-tab"
                  aria-current={selected === tab.page ? "page" : undefined}
                  onClick={() => go(tab.page)}
                >
                  {tab.label}
                </button>
              </li>
            ))}
          </ul>
        </nav>

        <div className="header-actions">
          {account ? (
            <ProfileMenu account={account} currentPage={currentPage} onNavigate={go} />
          ) : login ? (
            <button type="button" className="btn btn-primary btn-small" disabled={login.disabled} onClick={login.onClick}>
              {login.label}
            </button>
          ) : null}
        </div>
      </div>
    </header>
  );
}
