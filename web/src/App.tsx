
import { useState } from "react";
import { Authenticator } from "@aws-amplify/ui-react";
import "@aws-amplify/ui-react/styles.css";

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

function App() {
  const [showLogin, setShowLogin] = useState(false);
  const [currentPage, setCurrentPage] = useState<Page>("home");
  const [selectedEvent, setSelectedEvent] = useState<Event | null>(null);

  function navigate(page: Page) {
    setCurrentPage(page);
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
    setCurrentPage("purchase");

    if (!demoMode) {
      setShowLogin(true);
    }
  }

  function renderPage() {
    switch (currentPage) {
      case "survey":
        return <Survey />;

      case "recommendations":
        return <Recommendations />;

      case "artist":
        return <ArtistDashboard />;

      case "purchase":
        return selectedEvent ? (
          <Purchase
            event={selectedEvent}
            onBack={() => navigate("home")}
          />
        ) : (
          <Home onBuy={handleBuy} />
        );

      default:
        return <Home onBuy={handleBuy} />;
    }
  }

  function renderNavigation(includeArtist: boolean) {
    return (
      <div className="auth-navigation">
        <button
          type="button"
          onClick={() => navigate("home")}
        >
          Discover Events
        </button>

        <button
          type="button"
          onClick={() => navigate("survey")}
        >
          Music Preferences
        </button>

        <button
          type="button"
          onClick={() => navigate("recommendations")}
        >
          Recommended for You
        </button>

        {includeArtist && (
          <button
            type="button"
            onClick={() => navigate("artist")}
          >
            Artist Dashboard
          </button>
        )}
      </div>
    );
  }

  // Public website and demo mode.
  if (!showLogin) {
    return (
      <>
        {renderNavigation(demoMode)}

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

        {renderPage()}
      </>
    );
  }

  // Authenticated website.
  return (
    <div className="auth-page">
      <Authenticator loginMechanisms={["email"]}>
        {({ signOut, user }) => (
          <div>
            <div className="auth-navigation">
              <span>Welcome, {user?.username}</span>

              <button
                type="button"
                onClick={() => {
                  void signOut?.();
                  setShowLogin(false);
                  setCurrentPage("home");
                  setSelectedEvent(null);
                }}
              >
                Log out
              </button>
            </div>

            {renderNavigation(true)}
            {renderPage()}
          </div>
        )}
      </Authenticator>

      <button
        type="button"
        onClick={() => {
          setShowLogin(false);
          setCurrentPage("home");
        }}
      >
        Back to events
      </button>
    </div>
  );
}

export default App;
