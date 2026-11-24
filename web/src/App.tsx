
import { useEffect, useState } from "react";
import { Authenticator } from "@aws-amplify/ui-react";
import "@aws-amplify/ui-react/styles.css";

import {
  fetchAuthSession,
  fetchUserAttributes,
} from "aws-amplify/auth";

import Home from "./pages/Home";
import Survey from "./pages/Survey";
import Recommendations from "./pages/Recommendations";
import Purchase from "./pages/Purchase";
import ArtistDashboard from "./pages/ArtistDashboard";
import MyTickets from "./pages/MyTickets";
import ArtistSales from "./pages/ArtistSales";
import SiteHeader, { BrandLogo } from "./components/SiteHeader";

import type { Event } from "./components/EventCard";
import { PRIVATE_PAGES, type Page } from "./navigation";
import "./App.css";

const demoMode = import.meta.env.VITE_DEMO_MODE === "true";

const authConfigured = Boolean(
  import.meta.env.VITE_USER_POOL_ID &&
  import.meta.env.VITE_USER_POOL_CLIENT_ID
);

type PageContentProps = {
  page: Page;
  selectedEvent: Event | null;
  canPublish: boolean;
  onBuy: (event: Event) => void;
  navigate: (page: Page) => void;
};

function PageContent({
  page,
  selectedEvent,
  canPublish,
  onBuy,
  navigate,
}: PageContentProps) {
  switch (page) {
    case "survey":
      return <Survey />;

    case "recommendations":
      return <Recommendations onBuy={onBuy} />;

    case "mytickets":
      return <MyTickets />;

    // Hiding the menu links is cosmetic: these pages check the role again and
    // the API enforces the Cognito groups on every request.
    case "artist":
      return canPublish ? (
        <ArtistDashboard />
      ) : (
        <main className="container">
          <p className="notice notice-error" role="alert">
            Only approved artists and admins can publish events.
          </p>
        </main>
      );

    case "sales":
      return canPublish ? (
        <ArtistSales />
      ) : (
        <main className="container">
          <p className="notice notice-error" role="alert">
            Only approved artists and admins can see sales.
          </p>
        </main>
      );

    case "purchase":
      return selectedEvent ? (
        <Purchase
          event={selectedEvent}
          onBack={() => navigate("home")}
        />
      ) : (
        <Home onBuy={onBuy} />
      );

    default:
      return <Home onBuy={onBuy} />;
  }
}

type SignedInProps = {
  page: Page;
  selectedEvent: Event | null;
  navigate: (page: Page) => void;
  onBuy: (event: Event) => void;
  onLogout: () => void;
  signOut?: () => void | Promise<void>;
};

function SignedInArea({
  page,
  selectedEvent,
  navigate,
  onBuy,
  onLogout,
  signOut,
}: SignedInProps) {
  const [displayName, setDisplayName] = useState("User");
  const [email, setEmail] = useState<string | undefined>();
  const [canPublish, setCanPublish] = useState(false);
  const [profileLoading, setProfileLoading] = useState(true);
  const [profileError, setProfileError] = useState("");

  useEffect(() => {
    let active = true;

    async function loadProfile() {
      try {
        const [attributes, session] = await Promise.all([
          fetchUserAttributes(),
          fetchAuthSession(),
        ]);

        const rawGroups =
          session.tokens?.accessToken?.payload["cognito:groups"];

        const groups = Array.isArray(rawGroups)
          ? rawGroups.filter(
              (group): group is string =>
                typeof group === "string"
            )
          : [];

        if (!active) return;

        setDisplayName(
          attributes.name || attributes.email || "User"
        );
        setEmail(attributes.email);

        setCanPublish(
          groups.includes("artist") ||
          groups.includes("admin")
        );
      } catch {
        if (active) {
          setProfileError(
            "Could not load your account permissions."
          );
        }
      } finally {
        if (active) setProfileLoading(false);
      }
    }

    void loadProfile();

    return () => {
      active = false;
    };
  }, []);

  async function handleLogout() {
    if (!signOut) return;

    try {
      await signOut();
      onLogout();
    } catch {
      setProfileError("Logout failed. Please try again.");
    }
  }

  return (
    <>
      <SiteHeader
        currentPage={page}
        onNavigate={navigate}
        account={
          profileLoading
            ? undefined
            : {
                displayName,
                email,
                canPublish,
                onLogout: () => void handleLogout(),
              }
        }
      />

      {profileLoading ? (
        <main className="container">
          <p role="status">Loading account...</p>
        </main>
      ) : (
        <>
          {profileError && (
            <div className="container container-flush">
              <p className="notice notice-error" role="alert">
                {profileError}
              </p>
            </div>
          )}

          <PageContent
            page={page}
            selectedEvent={selectedEvent}
            canPublish={canPublish}
            onBuy={onBuy}
            navigate={navigate}
          />
        </>
      )}
    </>
  );
}

export default function App() {
  const [showLogin, setShowLogin] = useState(false);
  const [currentPage, setCurrentPage] = useState<Page>("home");
  const [selectedEvent, setSelectedEvent] =
    useState<Event | null>(null);

  function navigate(page: Page) {
    setCurrentPage(page);
    window.scrollTo({ top: 0 });

    // Private pages require login outside demo mode.
    if (!demoMode && PRIVATE_PAGES.includes(page)) {
      setShowLogin(true);
    }
  }

  function handleBuy(event: Event) {
    if (
      event.source === "ticketmaster" ||
      !event.capacity ||
      event.capacity <= 0
    ) {
      return;
    }

    setSelectedEvent(event);
    navigate("purchase");
  }

  if (showLogin && authConfigured) {
    return (
      <Authenticator
        loginMechanisms={["email"]}
        components={{
          Header() {
            return (
              <div className="auth-brand">
                <BrandLogo />
              </div>
            );
          },
          Footer() {
            return (
              <div className="auth-footer">
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => {
                    setShowLogin(false);
                    setCurrentPage("home");
                  }}
                >
                  ← Back to events
                </button>
              </div>
            );
          },
        }}
      >
        {({ signOut }) => (
          <SignedInArea
            page={currentPage}
            selectedEvent={selectedEvent}
            navigate={navigate}
            onBuy={handleBuy}
            signOut={signOut}
            onLogout={() => {
              setShowLogin(false);
              setCurrentPage("home");
              setSelectedEvent(null);
            }}
          />
        )}
      </Authenticator>
    );
  }

  return (
    <>
      <SiteHeader
        currentPage={currentPage}
        onNavigate={navigate}
        login={{
          label: authConfigured
            ? "Log in / Sign up"
            : "Login available after AWS deployment",
          disabled: !authConfigured,
          onClick: () => setShowLogin(true),
        }}
      />

      <PageContent
        page={currentPage}
        selectedEvent={selectedEvent}
        canPublish={false}
        onBuy={handleBuy}
        navigate={navigate}
      />
    </>
  );
}
