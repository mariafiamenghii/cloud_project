
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

import type { Event } from "./components/EventCard";
import "./App.css";

const demoMode = import.meta.env.VITE_DEMO_MODE === "true";

const authConfigured = Boolean(
  import.meta.env.VITE_USER_POOL_ID &&
  import.meta.env.VITE_USER_POOL_CLIENT_ID
);

type Page =
  | "home"
  | "survey"
  | "recommendations"
  | "purchase"
  | "artist";

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

    case "artist":
      return canPublish ? (
        <ArtistDashboard />
      ) : (
        <main className="container">
          <p role="alert">
            Only approved artists and admins can publish events.
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

type NavigationProps = {
  canPublish: boolean;
  navigate: (page: Page) => void;
};

function Navigation({ canPublish, navigate }: NavigationProps) {
  return (
    <nav className="auth-navigation" aria-label="Main navigation">
      <button type="button" onClick={() => navigate("home")}>
        Discover Events
      </button>

      <button type="button" onClick={() => navigate("survey")}>
        Music Preferences
      </button>

      <button
        type="button"
        onClick={() => navigate("recommendations")}
      >
        Recommended for You
      </button>

      {canPublish && (
        <button type="button" onClick={() => navigate("artist")}>
          Artist Dashboard
        </button>
      )}
    </nav>
  );
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

  if (profileLoading) {
    return <main className="container">Loading account...</main>;
  }

  return (
    <>
      <div className="auth-navigation">
        <span>Welcome, {displayName}</span>

        <button type="button" onClick={() => void handleLogout()}>
          Log out
        </button>
      </div>

      {profileError && (
        <p className="container" role="alert">
          {profileError}
        </p>
      )}

      <Navigation
        canPublish={canPublish}
        navigate={navigate}
      />

      <PageContent
        page={page}
        selectedEvent={selectedEvent}
        canPublish={canPublish}
        onBuy={onBuy}
        navigate={navigate}
      />
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

    // Private pages require login outside demo mode.
    if (
      !demoMode &&
      (page === "survey" ||
        page === "recommendations" ||
        page === "artist" ||
        page === "purchase")
    ) {
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
      <Authenticator loginMechanisms={["email"]}>
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
      <Navigation
        canPublish={false}
        navigate={navigate}
      />

      <div className="auth-navigation">
        <button
          type="button"
          disabled={!authConfigured}
          onClick={() => setShowLogin(true)}
        >
          {authConfigured
            ? "Log in / Sign up"
            : "Login available after AWS deployment"}
        </button>
      </div>

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
