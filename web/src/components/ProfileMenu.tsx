import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import type { Page } from "../navigation";

export type Account = {
  displayName: string;
  email?: string;
  // Only hides links; the pages and the API still check the user's Cognito groups.
  canPublish: boolean;
  onLogout: () => void;
};

type Props = {
  account: Account;
  currentPage: Page;
  onNavigate: (page: Page) => void;
};

function initials(name: string): string {
  const words = name.replace(/@.*/, "").split(/[\s._-]+/).filter(Boolean);
  const letters = words.length > 1 ? words[0][0] + words[1][0] : (words[0] ?? "?").slice(0, 2);
  return letters.toUpperCase();
}

export default function ProfileMenu({ account, currentPage, onNavigate }: Props) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const menuId = useId();

  const links: { page: Page; label: string }[] = [
    { page: "mytickets", label: "My Tickets" },
    ...(account.canPublish
      ? [
          { page: "artist" as const, label: "Association Dashboard" },
          { page: "sales" as const, label: "Sales" },
        ]
      : []),
  ];
  const onAccountPage = links.some((link) => link.page === currentPage);
  const currentLabel = links.find((link) => link.page === currentPage)?.label;

  const items = () => [...(menuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') ?? [])];

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  // Move focus into the menu when it opens.
  useEffect(() => {
    if (open) items()[0]?.focus();
  }, [open]);

  function close(returnFocus: boolean) {
    setOpen(false);
    if (returnFocus) buttonRef.current?.focus();
  }

  function onMenuKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const list = items();
    const index = list.indexOf(document.activeElement as HTMLButtonElement);
    const focusAt = (i: number) => list[(i + list.length) % list.length]?.focus();
    switch (event.key) {
      case "ArrowDown": event.preventDefault(); focusAt(index + 1); break;
      case "ArrowUp": event.preventDefault(); focusAt(index - 1); break;
      case "Home": event.preventDefault(); focusAt(0); break;
      case "End": event.preventDefault(); focusAt(list.length - 1); break;
      case "Escape": event.preventDefault(); close(true); break;
      case "Tab": setOpen(false); break;
    }
  }

  function choose(page: Page) {
    close(true);
    onNavigate(page);
  }

  return (
    <div className="profile" ref={rootRef}>
      <button
        ref={buttonRef}
        type="button"
        className={`profile-button${onAccountPage ? " is-current" : ""}`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((value) => !value)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" && !open) {
            event.preventDefault();
            setOpen(true);
          }
        }}
      >
        <span className="avatar" aria-hidden="true">{initials(account.displayName)}</span>
        <span className="profile-name">
          <span className="visually-hidden">Account menu for </span>
          {account.displayName}
          {currentLabel && <span className="profile-current">{currentLabel}</span>}
        </span>
        <span className="chevron" aria-hidden="true" />
      </button>

      {open && (
        <div id={menuId} ref={menuRef} className="profile-menu" role="menu" aria-label="Account" onKeyDown={onMenuKeyDown}>
          <div className="profile-menu-header" role="presentation">
            <strong>{account.displayName}</strong>
            {account.email && account.email !== account.displayName && <span>{account.email}</span>}
          </div>
          {links.map((link) => (
            <button
              key={link.page}
              type="button"
              role="menuitem"
              tabIndex={-1}
              className="profile-menu-item"
              aria-current={currentPage === link.page ? "page" : undefined}
              onClick={() => choose(link.page)}
            >
              {link.label}
            </button>
          ))}
          <div className="profile-menu-separator" role="separator" />
          <button
            type="button"
            role="menuitem"
            tabIndex={-1}
            className="profile-menu-item is-logout"
            onClick={() => {
              close(true);
              account.onLogout();
            }}
          >
            Log out
          </button>
        </div>
      )}
    </div>
  );
}
